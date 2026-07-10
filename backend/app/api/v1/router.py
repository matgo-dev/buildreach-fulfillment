from fastapi import APIRouter

from app.api.v1 import attachments, auth, customers

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(attachments.router)
api_router.include_router(customers.router)
