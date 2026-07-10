from fastapi import APIRouter

from app.api.v1 import attachments, auth, categories, customers, quotations, skus, spus, uploads

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(attachments.router)
api_router.include_router(customers.router)
api_router.include_router(categories.router)
api_router.include_router(spus.router)
api_router.include_router(skus.router)
api_router.include_router(quotations.router)
api_router.include_router(uploads.router)
