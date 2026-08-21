from fastapi import APIRouter

from app.api.v1 import (
    ap_credit_memos, attachments, auth, categories, customer_credit_memos, customer_returns, customers,
    inbound_orders, inventory, inventory_dispositions, outbound_orders,
    payables, payments, purchase_orders, purchase_returns, quotations, receipts, receivables,
    roles, sales_orders, shipments, skus, spus, suppliers, units, uploads, users, version,
)
from app.api.media import router as media_router
from app.api.v1.payments import alloc_router as payment_alloc_router
from app.api.v1.receipts import alloc_router as receipt_alloc_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(customers.router)
api_router.include_router(categories.router)
api_router.include_router(spus.router)
api_router.include_router(skus.router)
api_router.include_router(units.router)
api_router.include_router(quotations.router)
api_router.include_router(sales_orders.router)
api_router.include_router(suppliers.router)
api_router.include_router(purchase_orders.router)
api_router.include_router(purchase_returns.router)
api_router.include_router(ap_credit_memos.router)
api_router.include_router(customer_credit_memos.router)
api_router.include_router(customer_returns.router)
api_router.include_router(inbound_orders.router)
api_router.include_router(outbound_orders.router)
api_router.include_router(shipments.router)
api_router.include_router(inventory.router)
api_router.include_router(inventory_dispositions.router)
api_router.include_router(payables.router)
api_router.include_router(receivables.router)
api_router.include_router(receipts.router)
api_router.include_router(receipt_alloc_router)
api_router.include_router(payments.router)
api_router.include_router(payment_alloc_router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(uploads.router)
api_router.include_router(attachments.router)
api_router.include_router(media_router)
api_router.include_router(version.router)
