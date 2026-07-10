"""SPU 路由 /api/v1/spus。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.spu import SpuCreateIn, SpuOut
from app.services import spu_service

router = APIRouter(prefix="/spus", tags=["spus"])


@router.post("", summary="建 SPU")
async def create_spu(
    body: SpuCreateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.SPU_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    spu = await spu_service.create_spu(
        db, category_code=body.category_code, name_i18n=body.name_i18n,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(SpuOut.model_validate(spu, from_attributes=True).model_dump())
