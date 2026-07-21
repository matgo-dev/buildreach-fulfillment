from fastapi import APIRouter

from app.api.v1 import (
    attachments, auth, categories, customers, inbound_orders, inventory, outbound_orders,
    payables, purchase_orders, quotations, receivables, roles, sales_orders,
    shipments, skus, spus, suppliers, units, uploads, users,
)

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
api_router.include_router(inbound_orders.router)
api_router.include_router(outbound_orders.router)
api_router.include_router(shipments.router)
api_router.include_router(inventory.router)
api_router.include_router(payables.router)
api_router.include_router(receivables.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(uploads.router)
api_router.include_router(attachments.router)
