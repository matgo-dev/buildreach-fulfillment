"""收款单 RBAC + D9 门控:收款非红线(receipt:read 域),但内嵌应收明细额按 receivable:read 门控。

D9 = 权限跟数据走:只持 receipt:read 者经收款详情旁路看不到 AR 额(脱敏 null),仅见「冲了某张单」。
将来拆收付角色(留白 #8)时门已就位。
"""
import pytest

from tests.finance_helpers import make_open_receivable

pytestmark = pytest.mark.asyncio


async def _synth_headers(client, db_session, *, code, codes):
    """建合成角色(给定权限点)+ 账号,返回可用 headers。"""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.db.models.permission import Permission
    from app.db.models.role import Role, RoleScope
    from app.db.models.role_permission import RolePermission
    from app.db.models.user import User, UserStatus
    from app.db.models.user_role import UserRole
    from app.rbac.constants import Permissions

    role = Role(code=code, name=code, scope=RoleScope.GLOBAL, description="合成角色(测试)")
    db_session.add(role)
    await db_session.flush()
    all_codes = [Permissions.AUTH_LOGIN, Permissions.AUTH_LOGOUT, Permissions.AUTH_ME, *codes]
    perm_ids = (await db_session.execute(
        select(Permission.id).where(Permission.code.in_(all_codes)))).scalars().all()
    for pid in perm_ids:
        db_session.add(RolePermission(role_id=role.id, permission_id=pid))
    email, pw = f"{code.lower()}@fulfillment.local", "SynthPass123456"
    user = User(email=email, name=code, password_hash=hash_password(pw),
                status=UserStatus.ACTIVE, must_change_password=False)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


async def test_receipts_gated_403_without_receipt_read(client, sales_headers, logistics_headers):
    """SALES/LOGISTICS 无 receipt:read → 收款单 403(receipt:read 仅 FINANCE 持有)。"""
    assert (await client.get("/api/v1/receipts", headers=sales_headers)).status_code == 403
    assert (await client.get("/api/v1/receipts", headers=logistics_headers)).status_code == 403


async def test_receipt_detail_masks_ar_amount_without_receivable_read(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """D9:只持 receipt:read(无 receivable:read)者,收款详情内嵌核销记录的应收额脱敏为 null,
    但仍见「冲了某张单」(account_no)。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)
    reg = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "50.00",
        "received_at": "2026-07-21"})
    rid = reg.json()["data"]["receipt"]["id"]
    # FINANCE(持 receivable:read)看得到额
    fin = await client.get(f"/api/v1/receipts/{rid}", headers=finance_headers)
    assert float(fin.json()["data"]["allocations"][0]["amount"]) == 50.0

    # 合成角色:仅 receipt:read,无 receivable:read → 额脱敏 null,单号仍在
    ro = await _synth_headers(client, db_session, code="RECEIPT_RO_TEST",
                              codes=["receipt:read"])
    got = await client.get(f"/api/v1/receipts/{rid}", headers=ro)
    assert got.status_code == 200, got.text
    alloc = got.json()["data"]["allocations"][0]
    assert alloc["amount"] is None                 # 脱敏
    assert alloc["account_no"] is not None          # 仍见冲了某张单
