"""模型注册 —— 供 Base.metadata(create_all / alembic autogenerate)发现所有表。"""
from app.db.models.user import User
from app.db.models.role import Role, RoleCode
from app.db.models.permission import Permission
from app.db.models.user_role import UserRole
from app.db.models.role_permission import RolePermission
from app.db.models.audit_log import AuditLog
from app.db.models.category import Category  # noqa: F401
from app.db.models.category_spec_attribute import CategorySpecAttribute  # noqa: F401
from app.db.models.customer import Customer  # noqa: F401
from app.db.models.number_sequence import NumberSequence  # noqa: F401
from app.db.models.unit import Unit  # noqa: F401
from app.db.models.spu import Spu  # noqa: F401
from app.db.models.sku import Sku  # noqa: F401
from app.db.models.product_image import ProductImage  # noqa: F401
from app.db.models.quotation import QuotationOrder, QuotationLine  # noqa: F401
from app.db.models.sales_order import SalesOrder, SalesOrderLine  # noqa: F401
from app.db.models.supplier import Supplier  # noqa: F401
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine  # noqa: F401
from app.db.models.inbound_order import InboundOrder, InboundOrderLine  # noqa: F401
from app.db.models.payable import Payable  # noqa: F401
from app.db.models.shipment_order import ShipmentOrder  # noqa: F401
from app.db.models.shipment_event import ShipmentEvent  # noqa: F401
from app.db.models.outbound_order import OutboundOrder, OutboundOrderLine  # noqa: F401
from app.db.models.receivable import Receivable  # noqa: F401
from app.db.models.customs_declaration import CustomsDeclaration  # noqa: F401
from app.db.models.attachment import Attachment  # noqa: F401
from app.db.models.receipt import Receipt  # noqa: F401
from app.db.models.payment import Payment  # noqa: F401
from app.db.models.receipt_allocation import ReceiptAllocation  # noqa: F401
from app.db.models.payment_allocation import PaymentAllocation  # noqa: F401
from app.db.models.stock import InventoryBalance, InventoryMovement  # noqa: F401
from app.db.models.purchase_return import PurchaseReturnOrder, PurchaseReturnLine  # noqa: F401
from app.db.models.ap_credit_memo import APCreditMemo  # noqa: F401
from app.db.models.refresh_token_family import RefreshTokenFamily  # noqa: F401
from app.db.models.refresh_token import RefreshToken  # noqa: F401

__all__ = [
    "User", "Role", "RoleCode", "Permission",
    "UserRole", "RolePermission", "AuditLog", "Category",
    "CategorySpecAttribute", "Customer", "NumberSequence", "Unit", "Spu", "Sku",
    "ProductImage", "QuotationOrder", "QuotationLine", "SalesOrder", "SalesOrderLine",
    "Supplier", "PurchaseOrder", "PurchaseOrderLine",
    "InboundOrder", "InboundOrderLine", "Payable",
    "ShipmentOrder", "ShipmentEvent", "OutboundOrder", "OutboundOrderLine", "Receivable",
    "CustomsDeclaration", "Attachment",
    "Receipt", "Payment", "ReceiptAllocation", "PaymentAllocation",
    "InventoryBalance", "InventoryMovement", "PurchaseReturnOrder", "PurchaseReturnLine",
    "APCreditMemo",
    "RefreshTokenFamily", "RefreshToken",
]
