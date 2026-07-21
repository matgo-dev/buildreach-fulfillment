"""报关增量(主流程第10步):录/改/回填放行/软删 + 柜态守卫(42012)+ 每柜唯一(42013)+
越柜(42014)+ 乐观锁(42015)+ 撤封柜守卫(42011)+ 纯派生报关状态 + 列表筛选 + RBAC +
附件关联/级联软删。

前置:报关仅 LOADED/DEPARTED 柜可录。锁序:录改删先锁柜头,与撤封柜「无活动报关」串行化。
报关无红线字段(不含成本/供应商/售价)。
"""
import pytest

from tests.outbound_helpers import (
    create_and_confirm_outbound,
    create_shipment,
    make_loadable_shipment,
    setup_available_stock,
)

pytestmark = pytest.mark.asyncio

ATD = "2026-07-18"


async def _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """建到 LOADED 的柜(可录报关)。返回 (shipment_id, updated_at)。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    ship = d["shipment"]
    ld = await client.post(f"/api/v1/shipments/{ship['id']}/load", headers=logistics_headers,
                           json={"expected_updated_at": ship["updated_at"]})
    assert ld.status_code == 200, ld.text
    return ship["id"], ld.json()["data"]["shipment"]["updated_at"]


async def _loaded_from_stock(client, logistics_headers, *, so_id, so_line_id, qty=5):
    """从已有可发库存造一个 LOADED 柜(供同测试建多柜,不重建 catalog)。"""
    ship = await create_shipment(client, logistics_headers)
    _, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_line_id, "qty": qty}])
    assert conf.status_code == 200, conf.text
    ld = await client.post(f"/api/v1/shipments/{ship['id']}/load", headers=logistics_headers,
                           json={"expected_updated_at": ship["updated_at"]})
    assert ld.status_code == 200, ld.text
    return ship["id"]


async def _depart(client, logistics_headers, sid):
    r = await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers,
                          json={"atd": ATD})
    assert r.status_code == 200, r.text
    return r.json()["data"]["shipment"]["updated_at"]


async def _post_customs(client, headers, sid, **body):
    body.setdefault("declaration_no", "CN2026NBO0001")
    body.setdefault("declared_at", "2026-07-19")
    return await client.post(f"/api/v1/shipments/{sid}/customs-declarations",
                             headers=headers, json=body)


# ---------- 录入 + 派生状态 ----------


async def test_declare_then_release_full_flow(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """LOADED 柜录报关 → 详情嵌活动记录,状态派生 DECLARED;PATCH 回填放行 → RELEASED。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)

    # 未报关:详情 customs_status = NONE(LOADED 显未报关),customs_declaration = None。
    det = await client.get(f"/api/v1/shipments/{sid}", headers=logistics_headers)
    assert det.json()["data"]["customs_status"] == "NONE"
    assert det.json()["data"]["customs_declaration"] is None

    cr = await _post_customs(client, logistics_headers, sid, declarant="东非货代", customs_office="宁波")
    assert cr.status_code == 200, cr.text
    data = cr.json()["data"]
    assert data["customs_status"] == "DECLARED"
    decl = data["customs_declaration"]
    assert decl["declaration_no"] == "CN2026NBO0001" and decl["status"] == "DECLARED"
    assert decl["declarant"] == "东非货代" and decl["released_at"] is None
    decl_id, updated_at = decl["id"], decl["updated_at"]

    rel = await client.patch(
        f"/api/v1/shipments/{sid}/customs-declarations/{decl_id}", headers=logistics_headers,
        json={"released_at": "2026-07-25", "expected_updated_at": updated_at})
    assert rel.status_code == 200, rel.text
    rd = rel.json()["data"]
    assert rd["customs_status"] == "RELEASED"
    assert rd["customs_declaration"]["released_at"] == "2026-07-25"


async def test_declare_on_departed_shipment(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """DEPARTED 柜也可录报关(报关行代办跨离港)。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    await _depart(client, logistics_headers, sid)
    cr = await _post_customs(client, logistics_headers, sid)
    assert cr.status_code == 200, cr.text
    assert cr.json()["data"]["customs_status"] == "DECLARED"


async def test_declare_requires_loaded_or_departed_42012(client, logistics_headers):
    """OPEN 柜(未封柜)录报关 → 42012。"""
    ship = await create_shipment(client, logistics_headers)
    r = await _post_customs(client, logistics_headers, ship["id"])
    assert r.status_code == 409 and r.json()["code"] == 42012, r.text


async def test_duplicate_active_customs_42013(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """每柜至多一条活动报关:第二次录入 → 42013。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    assert (await _post_customs(client, logistics_headers, sid)).status_code == 200
    dup = await _post_customs(client, logistics_headers, sid, declaration_no="CN2026NBO0002")
    assert dup.status_code == 409 and dup.json()["code"] == 42013, dup.text


async def test_declno_taken_across_shipments_42016(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """报关单号活动期全局唯一:另一柜录同号 → 42016;PATCH 换成已占用单号 → 42016;
    改回自己当前单号(未变)不拦;占用记录软删后单号可复用。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=20, received=20)
    so_id, so_line_id = ctx["sales_order_id"], ctx["so_lines"][0]["id"]
    sid_a = await _loaded_from_stock(client, logistics_headers, so_id=so_id, so_line_id=so_line_id)
    sid_b = await _loaded_from_stock(client, logistics_headers, so_id=so_id, so_line_id=so_line_id)
    cr_a = await _post_customs(client, logistics_headers, sid_a, declaration_no="CN2026DUP01")
    assert cr_a.status_code == 200, cr_a.text
    # 跨柜同号录入 → 42016(柜头锁不串行化跨柜,预检 + 偏唯一兜底)。
    dup = await _post_customs(client, logistics_headers, sid_b, declaration_no="CN2026DUP01")
    assert dup.status_code == 409 and dup.json()["code"] == 42016, dup.text
    # B 柜录别的单号,再 PATCH 换成 A 柜占用的单号 → 42016。
    cr_b = await _post_customs(client, logistics_headers, sid_b, declaration_no="CN2026DUP02")
    decl_b = cr_b.json()["data"]["customs_declaration"]
    patch = await client.patch(f"/api/v1/shipments/{sid_b}/customs-declarations/{decl_b['id']}",
                               headers=logistics_headers,
                               json={"declaration_no": "CN2026DUP01",
                                     "expected_updated_at": decl_b["updated_at"]})
    assert patch.status_code == 409 and patch.json()["code"] == 42016, patch.text
    # PATCH 传自己当前单号(未变)不拦。
    same = await client.patch(f"/api/v1/shipments/{sid_b}/customs-declarations/{decl_b['id']}",
                              headers=logistics_headers,
                              json={"declaration_no": "CN2026DUP02", "note": "ok",
                                    "expected_updated_at": decl_b["updated_at"]})
    assert same.status_code == 200, same.text
    # 软删 A 柜记录 → 单号退出偏唯一,B 柜可换用。
    decl_a_id = cr_a.json()["data"]["customs_declaration"]["id"]
    await client.delete(f"/api/v1/shipments/{sid_a}/customs-declarations/{decl_a_id}",
                        headers=logistics_headers)
    freed = await client.patch(
        f"/api/v1/shipments/{sid_b}/customs-declarations/{decl_b['id']}",
        headers=logistics_headers,
        json={"declaration_no": "CN2026DUP01",
              "expected_updated_at": same.json()["data"]["customs_declaration"]["updated_at"]})
    assert freed.status_code == 200, freed.text


async def test_released_before_declared_rejected(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """放行日期早于申报日期 → DB CHECK 拒(500 级约束,或 service 校验)。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    r = await _post_customs(client, logistics_headers, sid,
                            declared_at="2026-07-19", released_at="2026-07-10")
    assert r.status_code >= 400, r.text  # CHECK 违约,不得落库


# ---------- 改 / 软删 / 乐观锁 ----------


async def test_update_optimistic_lock_42015(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """stale expected_updated_at 提交 → 42015(报关被他人改后)。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_customs(client, logistics_headers, sid)
    decl = cr.json()["data"]["customs_declaration"]
    stale = decl["updated_at"]
    # 先成功改一次,推进 updated_at。
    ok = await client.patch(f"/api/v1/shipments/{sid}/customs-declarations/{decl['id']}",
                            headers=logistics_headers,
                            json={"note": "查验中", "expected_updated_at": stale})
    assert ok.status_code == 200, ok.text
    # 用旧基线再提交 → 冲突。
    conflict = await client.patch(f"/api/v1/shipments/{sid}/customs-declarations/{decl['id']}",
                                  headers=logistics_headers,
                                  json={"declarant": "X", "expected_updated_at": stale})
    assert conflict.status_code == 409 and conflict.json()["code"] == 42015, conflict.text


async def test_update_null_required_field_rejected(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """PATCH 显式置空 declaration_no / declared_at → 400(NOT NULL 不可置空)。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_customs(client, logistics_headers, sid)
    decl = cr.json()["data"]["customs_declaration"]
    for body in ({"declaration_no": None}, {"declared_at": None}):
        r = await client.patch(f"/api/v1/shipments/{sid}/customs-declarations/{decl['id']}",
                               headers=logistics_headers,
                               json={**body, "expected_updated_at": decl["updated_at"]})
        assert r.status_code == 400, (body, r.text)


async def test_soft_delete_frees_shipment_for_redeclare(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """软删报关(纠错)后:退出偏唯一,可重录;详情回 NONE。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_customs(client, logistics_headers, sid)
    decl_id = cr.json()["data"]["customs_declaration"]["id"]
    dl = await client.delete(f"/api/v1/shipments/{sid}/customs-declarations/{decl_id}",
                             headers=logistics_headers)
    assert dl.status_code == 200, dl.text
    assert dl.json()["data"]["customs_declaration"] is None
    assert dl.json()["data"]["customs_status"] == "NONE"
    again = await _post_customs(client, logistics_headers, sid, declaration_no="CN2026NBO0009")
    assert again.status_code == 200, again.text


async def test_customs_not_on_shipment_42014_and_404(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """跨柜访问报关(记录属 A 柜,路径给 B 柜)→ 42014;记录不存在 → 404。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=20, received=20)
    so_id, so_line_id = ctx["sales_order_id"], ctx["so_lines"][0]["id"]
    sid_a = await _loaded_from_stock(client, logistics_headers, so_id=so_id, so_line_id=so_line_id)
    sid_b = await _loaded_from_stock(client, logistics_headers, so_id=so_id, so_line_id=so_line_id)
    cr = await _post_customs(client, logistics_headers, sid_a)
    decl_id = cr.json()["data"]["customs_declaration"]["id"]
    # B 柜路径访问 A 柜的报关记录。
    upd = await client.patch(f"/api/v1/shipments/{sid_b}/customs-declarations/{decl_id}",
                             headers=logistics_headers,
                             json={"note": "x", "expected_updated_at":
                                   cr.json()["data"]["customs_declaration"]["updated_at"]})
    assert upd.status_code == 400 and upd.json()["code"] == 42014, upd.text
    # 不存在 → 404。
    nf = await client.delete(f"/api/v1/shipments/{sid_a}/customs-declarations/999999",
                             headers=logistics_headers)
    assert nf.status_code == 404, nf.text


# ---------- 撤封柜守卫(42011)----------


async def test_unload_blocked_with_active_customs_42011(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """柜下有活动报关时撤封柜 → 42011;软删报关后撤封柜通过(纠错通路)。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_customs(client, logistics_headers, sid)
    decl_id = cr.json()["data"]["customs_declaration"]["id"]
    blocked = await client.post(f"/api/v1/shipments/{sid}/unload", headers=logistics_headers)
    assert blocked.status_code == 409 and blocked.json()["code"] == 42011, blocked.text
    await client.delete(f"/api/v1/shipments/{sid}/customs-declarations/{decl_id}",
                        headers=logistics_headers)
    ok = await client.post(f"/api/v1/shipments/{sid}/unload", headers=logistics_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["shipment"]["status"] == "OPEN"


# ---------- 列表派生列 + 筛选 ----------


async def test_list_derived_and_filter(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """列表派生报关状态列 + 筛选:未报关/已申报/已放行各命中对应柜;OPEN 柜 = None(显—)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=30, received=30)
    so_id, so_line_id = ctx["sales_order_id"], ctx["so_lines"][0]["id"]
    sid_none = await _loaded_from_stock(client, logistics_headers, so_id=so_id, so_line_id=so_line_id)
    sid_decl = await _loaded_from_stock(client, logistics_headers, so_id=so_id, so_line_id=so_line_id)
    await _post_customs(client, logistics_headers, sid_decl, declaration_no="CN2026NBO1001")
    sid_rel = await _loaded_from_stock(client, logistics_headers, so_id=so_id, so_line_id=so_line_id)
    cr = await _post_customs(client, logistics_headers, sid_rel, declaration_no="CN2026NBO1002")
    rd = cr.json()["data"]["customs_declaration"]
    await client.patch(f"/api/v1/shipments/{sid_rel}/customs-declarations/{rd['id']}",
                       headers=logistics_headers,
                       json={"released_at": "2026-07-26", "expected_updated_at": rd["updated_at"]})
    open_ship = await create_shipment(client, logistics_headers)

    lst = await client.get("/api/v1/shipments?size=100", headers=logistics_headers)
    by_id = {it["id"]: it for it in lst.json()["data"]["items"]}
    assert by_id[sid_none]["customs_status"] == "NONE"
    assert by_id[sid_decl]["customs_status"] == "DECLARED"
    assert by_id[sid_rel]["customs_status"] == "RELEASED"
    assert by_id[open_ship["id"]]["customs_status"] is None

    async def ids(cs: str) -> set[int]:
        r = await client.get(f"/api/v1/shipments?size=100&customs_status={cs}",
                             headers=logistics_headers)
        assert r.status_code == 200, r.text
        return {it["id"] for it in r.json()["data"]["items"]}

    none = await ids("NONE")
    assert sid_none in none and sid_decl not in none and open_ship["id"] not in none
    decl = await ids("DECLARED")
    assert sid_decl in decl and sid_none not in decl and sid_rel not in decl
    rel = await ids("RELEASED")
    assert sid_rel in rel and sid_decl not in rel and sid_none not in rel


# ---------- RBAC ----------


async def test_rbac_sales_read_only(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """SALES 只读:录/改/删报关全 403;详情报关字段可读(无红线字段)。"""
    sid, _ = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_customs(client, logistics_headers, sid)
    decl = cr.json()["data"]["customs_declaration"]

    post = await _post_customs(client, sales_headers, sid, declaration_no="X")
    assert post.status_code == 403, post.text
    patch = await client.patch(f"/api/v1/shipments/{sid}/customs-declarations/{decl['id']}",
                               headers=sales_headers,
                               json={"note": "x", "expected_updated_at": decl["updated_at"]})
    assert patch.status_code == 403
    dl = await client.delete(f"/api/v1/shipments/{sid}/customs-declarations/{decl['id']}",
                             headers=sales_headers)
    assert dl.status_code == 403
    det = await client.get(f"/api/v1/shipments/{sid}", headers=sales_headers)
    assert det.status_code == 200
    assert det.json()["data"]["customs_declaration"]["declaration_no"] == "CN2026NBO0001"


async def test_rbac_admin_cannot_manage_customs(client, superadmin_headers):
    """ADMIN 纯系统域不持 shipment:manage:录/改/删报关 403(权限守卫先于业务)。"""
    r = await client.post("/api/v1/shipments/1/customs-declarations", headers=superadmin_headers,
                          json={"declaration_no": "X", "declared_at": "2026-07-19"})
    assert r.status_code == 403, r.text
