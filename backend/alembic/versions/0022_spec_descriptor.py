"""0022 规格串增量:兜底 spec 属性下线 + 电子秤 division 结构化 + 快照/索引全量重算(data-only)

背景:早先每分类挂一个 key='spec' 的 string 兜底属性,值是自由文本(如电子秤 "15kg/0.5g"),
单据规格串因此又长又非结构化。本次把兜底 spec 拆成结构化变体轴(电子秤 → division 分度值,
number+unit g),并让行快照改成"只 SKU 轴、去标签、值+单位紧凑"的短串(见 compose_spec_text)。

顺序即依赖(每步幂等,可重跑):
① upsert division 模板行到 29.001(source=seed,与 seed 收敛)——必须先做,否则 ⑤ 拼不出 0.5g;
   29.001 分类不存在则跳过(WHERE EXISTS,不 FK 崩,与 seed skip-if-absent 一致)。
② 删 12 个兜底 spec 模板行(source=seed);
③ SKU spec_jsonb 重映射(自守卫,仅限 29.001 子树电子秤):只对「祖先链继承后能拿到 division
   模板(scope=sku)」且值可解析成 "Xkg/Yg" 的 SKU 把 {key:spec} 换成 {key:division,value:Y
   (数值)};其余(非电子秤品类误挂 key='spec'、或值解析不动)一律不动。remap 后加残留守卫:
   若仍有任何 SKU 含 key='spec' → raise RuntimeError 列出 sku 标识——alembic 单事务整体回滚,
   绝不静默产孤儿(数据超出本迁移预设即人工订正后重跑);
④ 受影响 SKU 重算 search_text(复用 build_sku_search_text 纯函数);
⑤ 4 张行表 spec_text_snapshot 全量重算:逐行按行自身 language,模板走祖先链继承合并(deep 覆
   shallow + 全局 rank,与 spec_template_service.get_suggestions 同规则),compose 复用
   compose_spec_text 纯函数。

downgrade:no-op —— 本迁移是数据订正(拆兜底 spec / 重算快照),无干净可逆语义;spec 原始自由
文本值已在 ③ 结构化后不再保留,不做假回滚。需回退请从备份恢复数据。

Revision ID: 0022_spec_descriptor
Revises: 0021_so_cancel
"""
from __future__ import annotations

import json
import re
from typing import Union

import sqlalchemy as sa
from alembic import op

# 纯函数复用(单一源头):拼串规则只在 compose_spec_text、search_text 只在 build_sku_search_text,
# 迁移不另抄一份,避免与运行时漂移。语义漂移由 test_spec_descriptor_migration 的终态断言看护
# (钉死 snap == "0.02–15kg / 0.5g" 等终态字符串,任何人改拼串语义该测试即红)。
from app.core.i18n import compose_spec_text
from app.core.search_text import build_sku_search_text

revision: str = "0022_spec_descriptor"
down_revision: Union[str, None] = "0021_so_cancel"
branch_labels = None
depends_on = None

# 挂过 key='spec' 兜底属性的 12 个分类(见 seed_data/spec_attributes.json 本次删除项)。
_SPEC_CODES = ("04", "06", "08", "13", "19", "21", "22", "23", "24", "26", "29", "32")

_LINE_TABLES = (
    "quotation_lines", "sales_order_lines", "purchase_order_lines", "inbound_order_lines",
)

_NUM = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)")


def _ancestor_codes(category_code: str) -> list[str]:
    """点分路径 code 的祖先链(含自身),从根到叶:与 spec_template_service._ancestor_codes 同约定。"""
    parts = category_code.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


def _suggestions_by_key(conn, category_code: str) -> dict[str, dict]:
    """祖先链继承合并(deep 覆 shallow)+ 全局单调 rank,复刻 get_suggestions 的合并规则(sync 版)。"""
    ancestors = _ancestor_codes(category_code)
    depth = {c: i for i, c in enumerate(ancestors)}
    stmt = sa.text(
        "SELECT id, category_code, key, label_i18n, value_type, options, unit, sort_order, scope "
        "FROM category_spec_attributes WHERE category_code IN :codes"
    ).bindparams(sa.bindparam("codes", expanding=True))
    rows = conn.execute(stmt, {"codes": ancestors}).mappings().all()
    merged: dict[str, dict] = {}
    for r in rows:
        cur = merged.get(r["key"])
        if cur is None or depth[r["category_code"]] > depth[cur["category_code"]]:
            merged[r["key"]] = r  # deep 覆 shallow:子类同名属性覆盖父类
    ordered = sorted(merged.values(), key=lambda r: (depth[r["category_code"]], r["sort_order"], r["id"]))
    out: dict[str, dict] = {}
    for rank, r in enumerate(ordered, start=1):
        out[r["key"]] = {
            "label_i18n": r["label_i18n"], "value_type": r["value_type"],
            "options": r["options"], "unit": r["unit"],
            "sort_order": rank * 10, "scope": r["scope"],
        }
    return out


def _parse_division(value) -> float | int | None:
    """从 "Xkg/Yg" 解析分度值 Y(取 '/' 后段、剥单位字符);解析不动返回 None(调用方跳过+告警)。"""
    if not isinstance(value, str) or "/" not in value:
        return None
    m = _NUM.match(value.split("/")[-1].strip())
    if not m:
        return None
    s = m.group(1)
    return float(s) if "." in s else int(s)  # 整数保持 int(1 不变 1.0)


def upgrade() -> None:
    _run(op.get_bind())


def _run(conn) -> None:
    """data 步骤本体(独立于 alembic op 上下文,吃一个 sync Connection)。
    抽出来是为迁移验证测试能在隔离临时库上直接驱动、并重复调用验幂等(见 tests)。"""
    # ① division 模板行 → 29.001(分类存在才插,ON CONFLICT 幂等,source=seed 与种子收敛)
    conn.execute(sa.text(
        "INSERT INTO category_spec_attributes "
        "(category_code, key, label_i18n, value_type, options, unit, sort_order, source, scope, "
        " created_at, updated_at) "
        "SELECT '29.001', 'division', '{\"zh\": \"分度值\", \"en\": \"Division\"}'::jsonb, "
        "       'number', NULL, 'g', "
        "       (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM category_spec_attributes "
        "        WHERE category_code = '29.001'), "
        "       'seed', 'sku', (now() at time zone 'utc'), (now() at time zone 'utc') "
        "WHERE EXISTS (SELECT 1 FROM categories WHERE code = '29.001') "
        "ON CONFLICT (category_code, key) DO NOTHING"
    ))

    # ② 删 12 个兜底 spec 模板行(仅 seed 来源;运营自建的另论,本迁移不碰)
    conn.execute(sa.text(
        "DELETE FROM category_spec_attributes "
        "WHERE key = 'spec' AND source = 'seed' AND category_code IN :codes"
    ).bindparams(sa.bindparam("codes", expanding=True)), {"codes": list(_SPEC_CODES)})

    by_key_cache: dict[str, dict] = {}

    def by_key(category_code: str) -> dict:
        if category_code not in by_key_cache:
            by_key_cache[category_code] = _suggestions_by_key(conn, category_code)
        return by_key_cache[category_code]

    # ③+④ 含 key='spec' 的 SKU:重映射 spec→division + 重算 search_text
    skus = conn.execute(sa.text(
        "SELECT s.id, s.spec_jsonb, s.name_i18n, s.sku_code, "
        "       p.category_code, p.name_i18n AS spu_name_i18n, p.brand, p.spec_jsonb AS spu_spec "
        "FROM skus s JOIN spus p ON p.id = s.spu_id "
        "WHERE s.spec_jsonb @> '[{\"key\": \"spec\"}]'::jsonb"
    )).mappings().all()

    for sku in skus:
        bk = by_key(sku["category_code"])
        # 自守卫①:非「祖先链能拿到 division 模板」的品类(如紧固件误挂 spec),本迁移一律不动,
        # 留给下方残留守卫兜底 raise;绝不静默把值往没有该模板的品类上错映射成 division。
        if "division" not in bk:
            continue
        new_items: list | None = []
        for it in (sku["spec_jsonb"] or []):
            if it.get("key") == "spec":
                d = _parse_division(it.get("value"))
                if d is None:
                    new_items = None
                    break
                new_items.append({"key": "division", "value": d})
            else:
                new_items.append(it)
        # 自守卫②:解析不动的值也不动(不产半吊子结果),同样留给残留守卫 raise。
        if new_items is None:
            continue

        search_text = build_sku_search_text(
            spu_name_i18n=sku["spu_name_i18n"], spu_brand=sku["brand"], spu_spec=sku["spu_spec"],
            sku_name_i18n=sku["name_i18n"], sku_spec=new_items, sku_code=sku["sku_code"],
            suggestions_by_key=bk)
        conn.execute(sa.text(
            "UPDATE skus SET spec_jsonb = CAST(:spec AS JSONB), search_text = :st WHERE id = :id"
        ), {"spec": json.dumps(new_items), "st": search_text, "id": sku["id"]})

    # 残留守卫(fail-loudly):remap 后仍含 key='spec' 的 SKU = 数据超出本迁移预设(仅 29.001
    # 子树电子秤)——非电子秤品类误挂、或电子秤值无法解析成 "Xkg/Yg"。② 已删模板,若放行这些
    # SKU 会变孤儿引用,故 raise 让 alembic 单事务整体回滚(库不脏),人工订正后重跑。
    residual = conn.execute(sa.text(
        "SELECT s.id, s.sku_code, p.category_code, s.spec_jsonb "
        "FROM skus s JOIN spus p ON p.id = s.spu_id "
        "WHERE s.spec_jsonb @> '[{\"key\": \"spec\"}]'::jsonb "
        "ORDER BY s.id"
    )).mappings().all()
    if residual:
        def _spec_val(items) -> object:
            for it in (items or []):
                if it.get("key") == "spec":
                    return it.get("value")
            return None
        detail = "; ".join(
            f"sku id={r['id']}(code={r['sku_code']}, 品类={r['category_code']}, "
            f"值={_spec_val(r['spec_jsonb'])!r})"
            for r in residual
        )
        raise RuntimeError(
            f"[0022] 残留 {len(residual)} 个 SKU 仍含 key='spec',数据超出本迁移预设(仅 29.001 "
            f"子树电子秤,值须为 \"Xkg/Yg\"):{detail}。请人工订正后重跑本迁移(alembic 单事务已回滚,库未变更)。"
        )

    # ⑤ 4 张行表 spec_text_snapshot 全量重算:逐行按行自身 language,只 SKU 轴(compose_spec_text)
    for table in _LINE_TABLES:
        lines = conn.execute(sa.text(
            f"SELECT l.id, l.language, s.spec_jsonb AS sku_spec, p.category_code "
            f"FROM {table} l JOIN skus s ON s.id = l.sku_id JOIN spus p ON p.id = s.spu_id"
        )).mappings().all()
        for ln in lines:
            spec_text = compose_spec_text(ln["sku_spec"] or [], by_key(ln["category_code"]), ln["language"])
            conn.execute(sa.text(
                f"UPDATE {table} SET spec_text_snapshot = :t WHERE id = :id"
            ), {"t": spec_text, "id": ln["id"]})


def downgrade() -> None:
    # 数据订正迁移,无干净可逆语义(spec 原始自由文本值已结构化,不保留);不做假回滚。
    # 需回退请从备份恢复。见模块 docstring。
    pass
