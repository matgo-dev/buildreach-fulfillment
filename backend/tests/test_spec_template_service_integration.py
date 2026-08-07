import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import ConflictError, SpecContractError
from app.db.models.category import Category
from app.db.models.category_spec_attribute import CategorySpecAttribute
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.services import sku_service
from app.services import spec_template_service as svc


async def _seed_cat(db, code="10"):
    db.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()


@pytest.mark.asyncio
async def test_get_suggestions_empty_when_none(db_session):
    await _seed_cat(db_session)
    assert await svc.get_suggestions(db_session, "10") == []


@pytest.mark.asyncio
async def test_upsert_new_key_writes_operator_source(db_session):
    await _seed_cat(db_session)
    item = await svc.upsert_attribute(
        db_session, "10", key="coating", label_i18n={"zh": "涂层"})
    assert item["key"] == "coating"
    assert item["source"] == "operator"
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert "coating" in by_key


@pytest.mark.asyncio
async def test_upsert_existing_key_is_noop_keeps_source(db_session):
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="material",
                               label_i18n={"zh": "材质"})
    # 再次 upsert 同 key(哪怕 label 不同)不覆盖已有——DB 层 ON CONFLICT DO NOTHING,
    # 不同 key 的并发 upsert 各自独立插行,不会互相踩踏丢更新(取代旧模型整包数组回写)。
    await svc.upsert_attribute(db_session, "10", key="material",
                               label_i18n={"zh": "改过的"})
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert by_key["material"]["label_i18n"] == {"zh": "材质"}
    assert len([s for s in await svc.get_suggestions(db_session, "10")
                if s["key"] == "material"]) == 1


@pytest.mark.asyncio
async def test_upsert_assigns_incrementing_sort_order(db_session):
    await _seed_cat(db_session)
    a = await svc.upsert_attribute(db_session, "10", key="a", label_i18n={"zh": "甲"})
    b = await svc.upsert_attribute(db_session, "10", key="b", label_i18n={"zh": "乙"})
    assert b["sort_order"] > a["sort_order"]


@pytest.mark.asyncio
async def test_upsert_enum_requires_options(db_session):
    await _seed_cat(db_session)
    with pytest.raises(Exception):
        await svc.upsert_attribute(
            db_session, "10", key="grade", label_i18n={"zh": "等级"}, value_type="enum")


@pytest.mark.asyncio
async def test_upsert_enum_with_options_roundtrips(db_session):
    await _seed_cat(db_session)
    options = [{"code": "hrb400", "label_i18n": {"zh": "HRB400"}}]
    item = await svc.upsert_attribute(
        db_session, "10", key="grade", label_i18n={"zh": "等级"},
        value_type="enum", options=options)
    assert item["options"] == options


@pytest.mark.asyncio
async def test_create_new_attribute_generates_random_ascii_key(db_session):
    """新属性 key 由应用层独立随机生成(a_ + 8 位 base62),绝非中文/用户原文,
    绝非 id/计数派生。两次调用互不相同(唯一性靠 UNIQUE(category_code,key) 兜底,
    极小概率撞键则内部换键重试)。"""
    await _seed_cat(db_session)
    item1 = await svc.create_new_attribute(db_session, "10", label_i18n={"zh": "涂层"})
    item2 = await svc.create_new_attribute(db_session, "10", label_i18n={"zh": "颜色"})
    for item in (item1, item2):
        key = item["key"]
        assert key.startswith("a_")
        suffix = key.removeprefix("a_")
        assert len(suffix) == 8 and suffix.isalnum()
    assert item1["key"] != item2["key"]
    assert item1["source"] == "operator"


@pytest.mark.asyncio
async def test_upsert_different_keys_both_persist_no_lost_update(db_session):
    """两次不同 key 的 upsert(模拟两人各给同类目加一个属性)都要落地——
    取代旧模型"整包数组读出来改一条再整包写回去"导致互相覆盖丢更新的根因。"""
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="alpha", label_i18n={"zh": "甲属性"})
    await svc.upsert_attribute(db_session, "10", key="beta", label_i18n={"zh": "乙属性"})
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert "alpha" in by_key and "beta" in by_key


# ── Task 14: inline 新增 enum 选项值(行锁追加 options) ──

async def _seed_enum_attr(db, code="10", key="material", options=None):
    await _seed_cat(db, code)
    options = options or [{"code": "carbon_steel", "label_i18n": {"zh": "碳钢"}}]
    await svc.upsert_attribute(db, code, key=key, label_i18n={"zh": "材质"},
                               value_type="enum", options=options)
    return options


@pytest.mark.asyncio
async def test_add_enum_option_generates_v_prefixed_code_and_appends(db_session):
    original_options = await _seed_enum_attr(db_session)
    code = await svc.add_enum_option(db_session, "10", "material", {"zh": "铝合金"})

    assert code.startswith("v_")
    suffix = code.removeprefix("v_")
    assert len(suffix) == 8 and suffix.isalnum()

    by_key = await svc.suggestions_by_key(db_session, "10")
    options = by_key["material"]["options"]
    assert options[0] == original_options[0]  # 既有选项原样保留
    assert {"code": code, "label_i18n": {"zh": "铝合金"}} in options
    assert len(options) == 2


@pytest.mark.asyncio
async def test_add_enum_option_rejects_label_without_zh(db_session):
    await _seed_enum_attr(db_session)
    with pytest.raises(Exception):
        await svc.add_enum_option(db_session, "10", "material", {"en": "Aluminum"})


@pytest.mark.asyncio
async def test_add_enum_option_rejects_non_enum_attribute(db_session):
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="dn", label_i18n={"zh": "公称通径"})
    with pytest.raises(Exception):
        await svc.add_enum_option(db_session, "10", "dn", {"zh": "新值"})


# ── 分类-属性继承:叶子拿到整条祖先链的并集(通用挂高层、特有挂低层)──

async def _seed_chain(db):
    """建一条真实形态的点分祖先链:30(金属管道 L1)→ 30.002(碳钢管道 L2)
    → 30.002.002(焊接钢管 L3,叶子)。parent_code 自引用 FK,父须先于子。"""
    db.add(Category(code="30", parent_code=None, name_i18n={"zh": "金属管道"},
                    level=1, is_leaf=False, sort_order=0))
    await db.flush()
    db.add(Category(code="30.002", parent_code="30", name_i18n={"zh": "碳钢管道"},
                    level=2, is_leaf=False, sort_order=0))
    await db.flush()
    db.add(Category(code="30.002.002", parent_code="30.002", name_i18n={"zh": "焊接钢管"},
                    level=3, is_leaf=True, sort_order=0))
    await db.flush()


@pytest.mark.asyncio
async def test_get_suggestions_inherits_whole_ancestor_chain(db_session):
    """叶子的建议 = 自身 + 所有上级属性的并集,按"通用→特有"顺序(祖先在前)。"""
    await _seed_chain(db_session)
    await svc.upsert_attribute(db_session, "30", key="dn", label_i18n={"zh": "公称直径"})
    await svc.upsert_attribute(db_session, "30.002", key="pn", label_i18n={"zh": "公称压力"})
    await svc.upsert_attribute(db_session, "30.002.002", key="wall", label_i18n={"zh": "壁厚"})

    keys = [s["key"] for s in await svc.get_suggestions(db_session, "30.002.002")]
    assert keys == ["dn", "pn", "wall"]  # 深度排序:L1 → L2 → L3


@pytest.mark.asyncio
async def test_get_suggestions_item_carries_owning_category_code(db_session):
    """每个建议项带**归属层** category_code——_resolve_spec 追加 enum 选项要写回这一层。"""
    await _seed_chain(db_session)
    await svc.upsert_attribute(db_session, "30", key="dn", label_i18n={"zh": "公称直径"})
    by_key = await svc.suggestions_by_key(db_session, "30.002.002")
    assert by_key["dn"]["category_code"] == "30"  # 归属在 L1,非叶子


@pytest.mark.asyncio
async def test_child_overrides_parent_same_key(db_session):
    """子类同名 key 覆盖父类(如把父层宽 enum 在子层收窄);取归属层为子层。"""
    await _seed_chain(db_session)
    await svc.upsert_attribute(
        db_session, "30", key="material", label_i18n={"zh": "材质"}, value_type="enum",
        options=[{"code": "carbon", "label_i18n": {"zh": "碳钢"}},
                 {"code": "ss", "label_i18n": {"zh": "不锈钢"}}])
    await svc.upsert_attribute(
        db_session, "30.002", key="material", label_i18n={"zh": "材质"}, value_type="enum",
        options=[{"code": "carbon", "label_i18n": {"zh": "碳钢"}}])  # 碳钢管道 → 收窄为仅碳钢

    by_key = await svc.suggestions_by_key(db_session, "30.002.002")
    assert by_key["material"]["category_code"] == "30.002"  # 深覆浅
    assert [o["code"] for o in by_key["material"]["options"]] == ["carbon"]


@pytest.mark.asyncio
async def test_get_suggestions_level1_code_unchanged_behavior(db_session):
    """传 L1 自身 code:祖先链=[自身],等价旧的精确匹配,不回归。"""
    await _seed_chain(db_session)
    await svc.upsert_attribute(db_session, "30", key="dn", label_i18n={"zh": "公称直径"})
    await svc.upsert_attribute(db_session, "30.002", key="pn", label_i18n={"zh": "公称压力"})
    keys = [s["key"] for s in await svc.get_suggestions(db_session, "30")]
    assert keys == ["dn"]  # 只有自身层,不含子层


# ── scope 分层:属性归属层(产品级 spu / 变体轴 sku)──

@pytest.mark.asyncio
async def test_upsert_default_scope_is_sku(db_session):
    await _seed_cat(db_session)
    item = await svc.upsert_attribute(db_session, "10", key="dn", label_i18n={"zh": "通径"})
    assert item["scope"] == "sku"  # 默认变体轴,向后兼容


@pytest.mark.asyncio
async def test_upsert_persists_and_returns_scope(db_session):
    await _seed_cat(db_session)
    item = await svc.upsert_attribute(
        db_session, "10", key="material", label_i18n={"zh": "材质"}, scope="spu")
    assert item["scope"] == "spu"
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert by_key["material"]["scope"] == "spu"


@pytest.mark.asyncio
async def test_create_new_attribute_scope(db_session):
    await _seed_cat(db_session)
    item = await svc.create_new_attribute(
        db_session, "10", label_i18n={"zh": "涂层"}, scope="spu")
    assert item["scope"] == "spu"


@pytest.mark.asyncio
async def test_chain_scope_conflict_rejected_ancestor(db_session):
    """父层 material=spu,子层再定义 material=sku → 拒绝(不变式5:链上同 key 单一 scope)。"""
    await _seed_chain(db_session)
    await svc.upsert_attribute(db_session, "30", key="material",
                               label_i18n={"zh": "材质"}, scope="spu")
    with pytest.raises(SpecContractError):
        await svc.upsert_attribute(db_session, "30.002", key="material",
                                   label_i18n={"zh": "材质"}, scope="sku")


@pytest.mark.asyncio
async def test_chain_scope_conflict_rejected_descendant(db_session):
    """先子层 material=sku,后父层 material=spu(顺序反过来)→ 一样拒绝(查祖先+后代)。"""
    await _seed_chain(db_session)
    await svc.upsert_attribute(db_session, "30.002", key="material",
                               label_i18n={"zh": "材质"}, scope="sku")
    with pytest.raises(SpecContractError):
        await svc.upsert_attribute(db_session, "30", key="material",
                                   label_i18n={"zh": "材质"}, scope="spu")


@pytest.mark.asyncio
async def test_chain_same_scope_override_ok(db_session):
    """子层可覆盖父层同 key(收窄),只要 scope 一致 → 放行。"""
    await _seed_chain(db_session)
    await svc.upsert_attribute(db_session, "30", key="material",
                               label_i18n={"zh": "材质"}, scope="spu")
    await svc.upsert_attribute(db_session, "30.002", key="material",
                               label_i18n={"zh": "材质"}, scope="spu")  # 同 scope,放行
    by_key = await svc.suggestions_by_key(db_session, "30.002.002")
    assert by_key["material"]["scope"] == "spu"


@pytest.mark.asyncio
async def test_sibling_same_key_different_scope_ok(db_session):
    """兄弟品类(非同一血统)同 key 不同 scope 允许——它们永不在同一继承链。"""
    from app.db.models.category import Category
    await _seed_chain(db_session)  # 30 / 30.002 / 30.002.002
    db_session.add(Category(code="30.003", parent_code="30", name_i18n={"zh": "不锈钢管道"},
                            level=2, is_leaf=True, sort_order=0))
    await db_session.flush()
    await svc.upsert_attribute(db_session, "30.002", key="grade",
                               label_i18n={"zh": "等级"}, scope="spu")
    # 兄弟 30.003 用同 key 不同 scope,不冲突
    await svc.upsert_attribute(db_session, "30.003", key="grade",
                               label_i18n={"zh": "等级"}, scope="sku")
    assert (await svc.suggestions_by_key(db_session, "30.003"))["grade"]["scope"] == "sku"


# ── resolve_spec 的 scope 守卫(键不重叠,不变式1)──

@pytest.mark.asyncio
async def test_resolve_spec_rejects_cross_scope_key(db_session):
    """在 SKU(scope=sku)写路径提交一个 spu 属性 → scope_mismatch 拒绝。"""
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="material",
                               label_i18n={"zh": "材质"}, scope="spu")
    with pytest.raises(SpecContractError):
        await svc.resolve_spec(db_session, "10",
                               [{"key": "material", "value": "x"}], scope="sku")


@pytest.mark.asyncio
async def test_resolve_spec_accepts_matching_scope(db_session):
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="dn",
                               label_i18n={"zh": "通径"}, scope="sku")
    out = await svc.resolve_spec(db_session, "10",
                                 [{"key": "dn", "value": "DN50"}], scope="sku")
    assert out == [{"key": "dn", "value": "DN50"}]


@pytest.mark.asyncio
async def test_resolve_spec_new_attribute_takes_write_scope(db_session):
    """内联新增属性(未知 key)落本次写入 scope(SPU 表单→spu)。"""
    await _seed_cat(db_session)
    out = await svc.resolve_spec(
        db_session, "10",
        [{"key": "抗震", "value": "8度", "label_i18n": {"zh": "抗震等级"}}], scope="spu")
    new_key = out[0]["key"]
    assert new_key.startswith("a_")
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert by_key[new_key]["scope"] == "spu"


# ── 并发一致性:商品规格写入与模板破坏性变更共用模板行锁 ──

async def _cleanup_committed_product_seed(Session, code: str) -> None:
    async with Session.begin() as db:
        spu_ids = select(Spu.id).where(Spu.category_code == code).scalar_subquery()
        await db.execute(delete(Sku).where(Sku.spu_id.in_(spu_ids)))
        await db.execute(delete(Spu).where(Spu.category_code == code))
        await db.execute(
            delete(CategorySpecAttribute).where(CategorySpecAttribute.category_code == code)
        )
        await db.execute(delete(Category).where(Category.code == code))


async def _seed_committed_product_with_enum_template(Session, code: str) -> int:
    await _cleanup_committed_product_seed(Session, code)
    async with Session.begin() as db:
        db.add(Category(code=code, parent_code=None, name_i18n={"zh": "并发品类"},
                        level=1, is_leaf=True, sort_order=0))
        await db.flush()
        await svc.upsert_attribute(
            db, code, key="material", label_i18n={"zh": "材质"},
            value_type="enum",
            options=[{"code": "v_old", "label_i18n": {"zh": "旧选项"}}],
            scope="sku",
        )
        spu = Spu(
            spu_code=f"SPU-{code}", category_code=code, name_i18n={"zh": "并发商品"},
            spec_jsonb=[], search_text="", created_by=1,
        )
        db.add(spu)
        await db.flush()
        return spu.id


async def _create_sku_referencing_old_option(Session, spu_id: int) -> Sku:
    async with Session() as db:
        return await sku_service.create_sku(
            db, spu_id=spu_id, unit="piece", reference_price=None,
            name_i18n={"zh": "并发 SKU"},
            spec_items=[{"key": "material", "value": "v_old"}],
            actor_user_id=1, actor_user_email="system@test", image_refs=[],
        )


async def _run_paused_sku_write(monkeypatch, Session, spu_id: int):
    locked_template = asyncio.Event()
    allow_commit = asyncio.Event()
    original_resolve_spec = svc.resolve_spec

    async def paused_resolve_spec(db, category_code, spec_items, *, scope="sku"):
        resolved = await original_resolve_spec(db, category_code, spec_items, scope=scope)
        locked_template.set()
        await allow_commit.wait()
        return resolved

    monkeypatch.setattr(svc, "resolve_spec", paused_resolve_spec)
    task = asyncio.create_task(_create_sku_referencing_old_option(Session, spu_id))
    await asyncio.wait_for(locked_template.wait(), timeout=2)
    return task, allow_commit


@pytest.mark.asyncio
async def test_delete_attribute_waits_for_concurrent_sku_write_then_conflicts(_engine, monkeypatch):
    """SKU 写入已解析合法模板但未提交时,删除属性必须等同一模板行锁释放;
    待 SKU 提交后重新查引用并冲突,不能留下商品引用已删除 key。"""
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    code = f"t{uuid4().hex[:10]}"
    spu_id = await _seed_committed_product_with_enum_template(Session, code)
    create_task = delete_task = None
    try:
        create_task, allow_commit = await _run_paused_sku_write(monkeypatch, Session, spu_id)

        async def delete_material():
            async with Session() as db:
                with pytest.raises(ConflictError, match="已有商品引用"):
                    await svc.delete_attribute(db, code, "material")

        delete_task = asyncio.create_task(delete_material())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(delete_task), timeout=0.2)

        allow_commit.set()
        created_sku = await create_task
        await delete_task
        assert created_sku.spec_jsonb == [{"key": "material", "value": "v_old"}]
    finally:
        if create_task is not None and not create_task.done():
            create_task.cancel()
        if delete_task is not None and not delete_task.done():
            delete_task.cancel()
        await _cleanup_committed_product_seed(Session, code)


@pytest.mark.asyncio
async def test_remove_enum_option_waits_for_concurrent_sku_write_then_conflicts(
    _engine, monkeypatch
):
    """SKU 写入引用 enum option 的事务未提交时,收缩 options 必须等待模板行锁;
    待 SKU 提交后看到 v_old 已被引用并拒绝删除该 option。"""
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    code = f"t{uuid4().hex[:10]}"
    spu_id = await _seed_committed_product_with_enum_template(Session, code)
    create_task = shrink_task = None
    try:
        create_task, allow_commit = await _run_paused_sku_write(monkeypatch, Session, spu_id)

        async def remove_old_option():
            async with Session() as db:
                with pytest.raises(ConflictError, match="枚举选项已被商品引用"):
                    await svc.update_attribute(
                        db, code, "material", label_i18n={"zh": "材质"},
                        value_type="enum",
                        options=[{"code": "v_new", "label_i18n": {"zh": "新选项"}}],
                        scope="sku",
                    )

        shrink_task = asyncio.create_task(remove_old_option())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(shrink_task), timeout=0.2)

        allow_commit.set()
        created_sku = await create_task
        await shrink_task
        assert created_sku.spec_jsonb == [{"key": "material", "value": "v_old"}]
    finally:
        if create_task is not None and not create_task.done():
            create_task.cancel()
        if shrink_task is not None and not shrink_task.done():
            shrink_task.cancel()
        await _cleanup_committed_product_seed(Session, code)
