"""分类规格属性模板服务:一属性一行(category_spec_attributes),按行 upsert 幂等。

一属性一行(而非分类挂一个 JSONB 数组):DB 层 UNIQUE(category_code,key) 保证唯一;
两个不同 key 的 upsert 各自独立插自己的行,互不覆盖,天然无整包数组读改写(read-
modify-write)的丢更新问题。
"""
from __future__ import annotations

import secrets
import string

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SpecContractError
from app.db.models.category_spec_attribute import CategorySpecAttribute, SuggestionSource
from app.schemas.sku import validate_spec_items

_KEY_ALPHABET = string.ascii_letters + string.digits


def _random_attribute_key() -> str:
    """独立随机稳定键(前缀 a_ + 8 位 base62)——身份本身随机生成,不是任何 id/计数/
    时间的派生,也绝非用户原文/中文。用 secrets(非 random)保证不可预测。"""
    return "a_" + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(8))


def _random_option_code() -> str:
    """enum 选项 code:前缀 v_ + 8 位 base62,规矩同 _random_attribute_key(独立随机、
    稳定、非中文、不翻译,secrets 生成)。"""
    return "v_" + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(8))


def _to_item(row: CategorySpecAttribute) -> dict:
    return {
        "key": row.key,
        "label_i18n": row.label_i18n,
        "value_type": row.value_type,
        "options": row.options,
        "unit": row.unit,
        "sort_order": row.sort_order,
        "source": row.source,
        # 属性归属层的 category_code:继承合并后同 key 可能来自祖先层(见 get_suggestions),
        # 消费端(如 _resolve_spec 追加 enum 选项)必须回写到属性真正所在的那一层,
        # 而不是叶子层——否则写到不存在该属性的层会失败。
        "category_code": row.category_code,
        "scope": row.scope,  # 'spu' 产品级 / 'sku' 变体轴——前端按此分渲染到 SPU/SKU 表单
    }


def _ancestor_codes(category_code: str) -> list[str]:
    """点分路径 code 的祖先链(含自身),从根到叶:
    "30.002.002" → ["30", "30.002", "30.002.002"]。

    分类 code 是点分层级路径且唯一、永久契约(与子树前缀过滤 `code LIKE code||'.%'`
    同一套约定),祖先即各级前缀,无需再查 parent_code 递归。
    """
    parts = category_code.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


def _validate_label_and_options(label_i18n: dict, value_type: str, options: list[dict] | None) -> None:
    if not label_i18n.get("zh"):
        raise SpecContractError("label_i18n.zh 必填")
    if any(v in ("", None) for v in label_i18n.values()):
        raise SpecContractError("label_i18n 禁止空串/空值")
    if value_type == "enum" and not options:
        raise SpecContractError("enum 属性必须提供 options")
    if value_type != "enum" and options:
        raise SpecContractError("非 enum 属性不可携带 options")


async def get_suggestions(db: AsyncSession, category_code: str) -> list[dict]:
    """解析某分类的建议属性 = **整条祖先链的并集**(通用属性挂高层、特有属性挂低层,
    叶子继承全套)——对齐 PIM/ERP 的分类-属性继承(Akeneo family / SAP class 层级)。

    - 取值域:商品只能挂叶子分类(spu_service._get_leaf_category),故消费方传进来的
      是叶子 code;这里按点分祖先链把该叶子与所有上级的属性一起取出。
    - 归并规则:同 key **深覆浅**(子类可覆盖父类同名属性,如把父层宽 enum 收窄、
      或改 label);每个 (category_code,key) 由 DB UNIQUE 保证至多一行,不会层内撞。
    - 排序:先按归属层深度、再按该层 sort_order、再 id;返回项的 sort_order 重排成
      全局单调 rank(×10),使跨层不撞、compose_spec_text 按 sort_order 排序稳定。
    """
    ancestors = _ancestor_codes(category_code)
    depth = {code: i for i, code in enumerate(ancestors)}
    rows = (await db.execute(
        select(CategorySpecAttribute)
        .where(CategorySpecAttribute.category_code.in_(ancestors))
    )).scalars().all()

    merged: dict[str, CategorySpecAttribute] = {}
    for row in rows:
        cur = merged.get(row.key)
        if cur is None or depth[row.category_code] > depth[cur.category_code]:
            merged[row.key] = row  # 深覆浅:子类同名属性覆盖父类

    ordered = sorted(
        merged.values(),
        key=lambda r: (depth[r.category_code], r.sort_order, r.id),
    )
    items = []
    for rank, row in enumerate(ordered, start=1):
        item = _to_item(row)
        item["sort_order"] = rank * 10  # 归并后的全局单调序,替代各层各自的 sort_order
        items.append(item)
    return items


async def suggestions_by_key(db: AsyncSession, category_code: str) -> dict[str, dict]:
    return {s["key"]: s for s in await get_suggestions(db, category_code)}


async def _next_sort_order(db: AsyncSession, category_code: str) -> int:
    return (await db.execute(
        select(func.coalesce(func.max(CategorySpecAttribute.sort_order), 0) + 10)
        .where(CategorySpecAttribute.category_code == category_code)
    )).scalar_one()


async def _assert_chain_scope_consistent(
    db: AsyncSession, category_code: str, key: str, scope: str) -> None:
    """不变式5:一条叶子的继承链上,同 key 各层 scope 必须一致。

    冲突面 = 本品类的祖先(点分前缀)∪ 后代(前缀子树);兄弟品类不同血统、永不同链,放行。
    已知键的 upsert 前调用:同 key 在血统里已存在且 scope 不同 → SpecContractError
    (随机键的 create_new_attribute 天然不撞键,无需此检查)。
    """
    rows = (await db.execute(
        select(CategorySpecAttribute.category_code, CategorySpecAttribute.scope)
        .where(CategorySpecAttribute.key == key)
        .where(or_(
            CategorySpecAttribute.category_code.in_(_ancestor_codes(category_code)),
            CategorySpecAttribute.category_code.like(category_code + ".%"),
        ))
    )).all()
    for cat, existing_scope in rows:
        if cat != category_code and existing_scope != scope:
            raise SpecContractError(
                f"scope_conflict_in_chain: key={key!r} 在 {cat!r}(scope={existing_scope})"
                f"与 {category_code!r}(scope={scope})冲突——同继承链同 key 须单一 scope")


async def upsert_attribute(
    db: AsyncSession,
    category_code: str,
    *,
    key: str,
    label_i18n: dict,
    value_type: str = "string",
    unit: str | None = None,
    options: list[dict] | None = None,
    source: str = SuggestionSource.OPERATOR,
    scope: str = "sku",
) -> dict:
    """已知 key 的按行幂等 upsert:key 已存在则原样返回不覆盖(保持模板稳定,不因
    重复提交漂移)。调用方须已确定这个 key(种子的人工键,或已在模板中的既有 key)
    ——生成全新随机 key 走 create_new_attribute,不要在这里传一个刚现造的 key。

    单行 INSERT ... ON CONFLICT(category_code,key) DO NOTHING + 回读:不同 key 各自一行,
    并发 upsert 不同 key 永远不会互相踩踏丢更新(无需整包数组读改写)。

    scope:'spu' 产品级 / 'sku' 变体轴(默认)。插入前守卫继承链同 key 单一 scope(不变式5)。
    """
    _validate_label_and_options(label_i18n, value_type, options)
    await _assert_chain_scope_consistent(db, category_code, key, scope)

    next_order = await _next_sort_order(db, category_code)
    stmt = insert(CategorySpecAttribute).values(
        category_code=category_code, key=key, label_i18n=label_i18n,
        value_type=value_type, options=options, unit=unit or "",
        sort_order=next_order, source=source, scope=scope,
    ).on_conflict_do_nothing(index_elements=["category_code", "key"])
    await db.execute(stmt)
    await db.flush()

    row = (await db.execute(select(CategorySpecAttribute).where(
        CategorySpecAttribute.category_code == category_code,
        CategorySpecAttribute.key == key,
    ))).scalar_one()
    return _to_item(row)


async def create_new_attribute(
    db: AsyncSession,
    category_code: str,
    *,
    label_i18n: dict,
    value_type: str = "string",
    unit: str | None = None,
    options: list[dict] | None = None,
    source: str = SuggestionSource.OPERATOR,
    scope: str = "sku",
    max_retries: int = 5,
) -> dict:
    """运营新增属性:后端生成独立随机稳定键(a_<8位 base62>)并落一行,不接受调用方
    指定 key(禁止把中文/用户原文当 key)。

    scope:'spu'(SPU 表单加的)/ 'sku'(SKU 表单加的,默认)——由调用表单传入。随机键
    天然不与既有键碰撞,故不需要链上 scope 检查(不会踩到别层同名 key)。

    插入前生成、一次 INSERT、不回填、不派生自 id —— key 列存的是真身份(独立随机),
    不是内部自增 PK 的派生;别把内部 PK 当外部契约暴露,id 管内部 join,key 管对外引用
    (spec_jsonb 消费端只看得到 key,种子的人工键与这里的随机键一视同仁)。

    唯一性由 UNIQUE(category_code,key) 兜底:INSERT ... ON CONFLICT DO NOTHING
    RETURNING id,极小概率撞键(RETURNING 空)则换个随机键重试,不抛异常不回滚。
    """
    _validate_label_and_options(label_i18n, value_type, options)

    for _ in range(max_retries):
        key = _random_attribute_key()
        next_order = await _next_sort_order(db, category_code)
        stmt = (
            insert(CategorySpecAttribute)
            .values(
                category_code=category_code, key=key, label_i18n=label_i18n,
                value_type=value_type, options=options, unit=unit or "",
                sort_order=next_order, source=source, scope=scope,
            )
            .on_conflict_do_nothing(index_elements=["category_code", "key"])
            .returning(CategorySpecAttribute.id)
        )
        row_id = (await db.execute(stmt)).scalar_one_or_none()
        if row_id is not None:
            await db.flush()
            row = (await db.execute(select(CategorySpecAttribute).where(
                CategorySpecAttribute.id == row_id))).scalar_one()
            return _to_item(row)
        # 撞键(概率 ~1/62^8,几乎不会触发):换个随机键重试

    raise SpecContractError("生成属性 key 连续冲突,请重试")


async def add_enum_option(
    db: AsyncSession,
    category_code: str,
    key: str,
    label_i18n: dict,
    *,
    max_retries: int = 5,
) -> str:
    """inline 新增 enum 选项值(运营在录 SKU 时发现现有 options 缺值,如"材质"缺
    "铝合金"):追加进属性行 options JSONB 数组,返回新生成的 code。

    并发坑:options 是属性行上的一整个 JSONB 数组,追加 = read-modify-write
    (CT11 把属性正规化成一属性一行,正是为了躲开这个;但 options 数组本身没法再拆表)。
    这里用 `SELECT ... FOR UPDATE` 锁该属性行:锁住之后再读到的 options 一定是最新的,
    追加完 flush 前锁一直持有,另一并发追加会等到本事务提交后才拿到锁、读到已包含本次
    追加的最新数组,不会互相踩踏丢更新。grain 是单属性、选项数量少、并发概率极低,
    行锁足够,不需要为此再拆一张 options 表。

    code 生成规矩同属性键(_random_attribute_key):独立随机、v_ 前缀、8 位 base62、
    secrets 生成、绝非中文/用户原文的翻译或派生。不按 label 去重——同一属性下选项集
    通常很小,防重复主要靠前端下拉里优先展示已有选项,和属性键一样只认生成 code
    这一个身份维度。
    """
    if not label_i18n.get("zh"):
        raise SpecContractError("label_i18n.zh 必填")
    if any(v in ("", None) for v in label_i18n.values()):
        raise SpecContractError("label_i18n 禁止空串/空值")

    row = (await db.execute(
        select(CategorySpecAttribute)
        .where(CategorySpecAttribute.category_code == category_code, CategorySpecAttribute.key == key)
        .with_for_update()
    )).scalar_one_or_none()
    if row is None:
        raise SpecContractError(f"属性不存在: category_code={category_code!r} key={key!r}")
    if row.value_type != "enum":
        raise SpecContractError(f"属性 '{key}' 非 enum 类型,不支持追加选项")

    existing_codes = {opt["code"] for opt in (row.options or [])}
    for _ in range(max_retries):
        code = _random_option_code()
        if code not in existing_codes:
            break
    else:
        raise SpecContractError("生成选项 code 连续冲突,请重试")

    # 整个新 list 重新赋值(而非原地 .append)——SQLAlchemy 靠属性重赋值侦测变更,
    # 不依赖 MutableList 包装即可正确 UPDATE。
    row.options = [*(row.options or []), {"code": code, "label_i18n": label_i18n}]
    await db.flush()
    return code


async def resolve_spec(
    db: AsyncSession, category_code: str, spec_items: list[dict], *, scope: str = "sku"
) -> list[dict]:
    """校验 + 新属性生成稳定键回写模板;返回落库用的 spec_jsonb(仅 key/value)。
    SPU(scope='spu')与 SKU(scope='sku')写路径共用此解析器,scope 分层。

    scope 守卫(不变式1,键不重叠):提交 key 的模板 scope 必须 == 本次写入 scope,否则
    `spec.scope_mismatch`——防把产品级 key 写进 SKU 或反之,保证两 spec_jsonb 物理不重叠。

    身份≠展示铁律:key 在模板里 → 直接用该 key;不在模板 → 后端生成独立随机稳定键
    `a_<8位 base62>`(create_new_attribute,带本次 scope),把用户 label_i18n(zh 必填)落回
    模板,SKU/SPU 引用生成键。未知 key 又没带 label_i18n → SpecContractError。

    enum:填的 value 必须 ∈ 模板 options code;不在且带 label_i18n → inline 新增选项
    (add_enum_option,写回属性归属层,继承后可能是祖先层);既不在又没 label → 报错。

    计量单位归位:单位只住模板 unit,spec_jsonb 永不落 unit;提交的 unit 仅"新增属性"分支
    消费一次(作该新属性模板行单位),已存在 key 的提交 unit 一律忽略。
    """
    known = await suggestions_by_key(db, category_code)  # 含继承、全 scope
    resolved: list[dict] = []
    for item in spec_items:
        key = item.get("key")
        tmpl_row = known.get(key) if key else None
        value = item.get("value")
        if tmpl_row is not None and tmpl_row["scope"] != scope:
            raise SpecContractError(
                f"scope_mismatch: 属性 {key!r} 属 {tmpl_row['scope']} 层,"
                f"不能在 {scope} 表单提交")
        if tmpl_row is None:
            label_i18n = item.get("label_i18n")
            if not label_i18n or not label_i18n.get("zh"):
                raise SpecContractError(
                    f"未知属性 key={key!r}:模板中不存在,新增属性须带 label_i18n(zh 必填)")
            tmpl_row = await create_new_attribute(
                db, category_code, label_i18n=label_i18n, value_type="string",
                unit=item.get("unit") or None, scope=scope)
            key = tmpl_row["key"]
            known[key] = tmpl_row
        elif tmpl_row.get("value_type") == "enum":
            codes = {opt["code"] for opt in (tmpl_row.get("options") or [])}
            if not (isinstance(value, str) and value in codes):
                label_i18n = item.get("label_i18n")
                if not label_i18n or not label_i18n.get("zh"):
                    raise SpecContractError(
                        f"属性 '{key}' 的值 {value!r} 不在允许的 enum code 集 {sorted(codes)} 内")
                # 追加到属性**归属层**(继承后可能是祖先层),对该层所有后代叶子共享。
                new_code = await add_enum_option(
                    db, tmpl_row["category_code"], key, label_i18n)
                tmpl_row["options"] = [*(tmpl_row.get("options") or []),
                                       {"code": new_code, "label_i18n": label_i18n}]
                known[key] = tmpl_row
                value = new_code
        resolved.append({"key": key, "value": value})
    parsed = validate_spec_items(resolved)
    return [p.model_dump(exclude_none=True) for p in parsed]


async def resolve_spec_display(
    db: AsyncSession, category_code: str, spec_items: list[dict]) -> list[dict]:
    """spec_jsonb(仅 key/value)→ 展示投影(后端单一源头):
    `[{key, label_i18n, value, unit, scope}]`。列表/详情/报价统一消费,不各拼各的。

    - value:enum 取选中 option 的 `label_i18n`(i18n dict,前端按语言 display);
      string/number 原样(标量)。
    - 排序:产品级(spu)在前、轴(sku)在后,再按模板 sort_order。
    - 传入 = SPU 产品级 ∪ SKU 轴的并集(调用方合并两 spec_jsonb),故读时并集在这里成形。

    批量场景(SKU 搜索按分类缓存 by_key)复用纯投影 project_spec_display,避免每行一查模板。
    """
    by_key = await suggestions_by_key(db, category_code)
    return project_spec_display(spec_items, by_key)


def project_spec_display(spec_items: list[dict], by_key: dict[str, dict]) -> list[dict]:
    """resolve_spec_display 的纯投影部分(不查库):给定 by_key 把 spec_jsonb 投影成展示项。
    单一源头,resolve_spec_display 与 SKU 搜索批量投影共用,避免两处拼法漂移。"""
    out = []
    for item in spec_items or []:
        t = by_key.get(item.get("key"), {})
        value = item.get("value")
        if t.get("value_type") == "enum":
            for opt in (t.get("options") or []):
                if opt.get("code") == value:
                    value = opt.get("label_i18n")
                    break
        out.append({
            "key": item.get("key"),
            "label_i18n": t.get("label_i18n"),
            "value": value,
            "unit": t.get("unit") or "",
            "scope": t.get("scope"),
            "_sort": (0 if t.get("scope") == "spu" else 1, t.get("sort_order", 9999)),
        })
    out.sort(key=lambda d: d["_sort"])
    for d in out:
        d.pop("_sort")
    return out
