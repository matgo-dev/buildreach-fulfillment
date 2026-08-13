"""出库单空行守卫(service 层兜底)。

API schema 对 create/save 有 lines min_length=1(空 → 422),挡不到 service 直调。
本组测试直调 outbound_service,验证 0 行出库单在**建单/确认**两处被 service 兜底拒绝(41911):
- 0 行草稿会占「同柜同 SO」草稿槽位(_assert_no_draft_order 计 status=DRAFT);
- 0 行确认会生成 0 金额应收(镜像采购 confirm 的 PurchaseOrderEmptyError)。
"""
import pytest
from sqlalchemy import delete, select

from app.core.exceptions import OutboundOrderEmptyError
from app.db.models.outbound_order import OutboundOrderLine
from app.db.models.user import User
from app.services import outbound_service
from tests.outbound_helpers import create_outbound, create_shipment, setup_available_stock

_LOGISTICS_EMAIL = "logistics@fulfillment.local"


async def _logistics_uid(db_session) -> int:
    return (await db_session.execute(
        select(User.id).where(User.email == _LOGISTICS_EMAIL))).scalar_one()


@pytest.mark.asyncio
async def test_create_outbound_empty_lines_rejected_at_service(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """service 直调建 0 行出库单被拒(41911)—— 守卫在 _validate_lines_in_so,建单/编辑共守。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    ship = await create_shipment(client, logistics_headers)
    uid = await _logistics_uid(db_session)
    with pytest.raises(OutboundOrderEmptyError):
        await outbound_service.create_order(
            db_session, sales_order_id=ctx["sales_order_id"], shipment_id=ship["id"],
            note=None, lines=[], actor_user_id=uid, actor_user_email=_LOGISTICS_EMAIL)


@pytest.mark.asyncio
async def test_confirm_outbound_empty_lines_rejected_at_service(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """确认一张被清空行的出库单被拒(41911)—— 防 0 金额应收 + 柜误判非空。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    ship = await create_shipment(client, logistics_headers)
    cr = await create_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"], lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 5}])
    assert cr.status_code == 200, cr.text
    ob_id = cr.json()["data"]["order"]["id"]
    # 直接删空行,模拟「0 行出库单」态,验证 confirm 兜底(正常路径进不来,故直操 DB)。
    await db_session.execute(
        delete(OutboundOrderLine).where(OutboundOrderLine.outbound_order_id == ob_id))
    await db_session.commit()
    uid = await _logistics_uid(db_session)
    with pytest.raises(OutboundOrderEmptyError):
        await outbound_service.confirm_order(
            db_session, order_id=ob_id, actor_user_id=uid, actor_user_email=_LOGISTICS_EMAIL)
