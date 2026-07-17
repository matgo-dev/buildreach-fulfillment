"""service 层通用 DB 访问件:按 id 取行(404 / 悲观锁)+ 分页 + 乐观锁比对。

只收敛执行代码;各域错误类 / 错误消息 / 额外过滤条件(如软删)由调用方传入,不合并语义。
"""
from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_404(db: AsyncSession, model, obj_id, *, error_cls, message: str,
                     for_update: bool = False, extra_where: tuple = ()):
    """按主键取行,查无抛 error_cls(message)。for_update=True 走 SELECT ... FOR UPDATE
    行级悲观锁(锁持到本事务提交,串行化"读→改→写"写路径);extra_where 追加过滤
    (如软删 deleted_at IS NULL)。"""
    stmt = select(model).where(model.id == obj_id, *extra_where)
    if for_update:
        stmt = stmt.with_for_update()
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise error_cls(message)
    return obj


async def paginate(db: AsyncSession, stmt: Select, *, page: int, size: int,
                   count_stmt: Select | None = None, scalars: bool = True) -> tuple[list, int]:
    """count + 切页(offset/limit)。stmt 由调用方带好筛选/排序,此处只负责总数与分页执行。

    count_stmt 缺省时由 stmt 去排序后包子查询派生;调用方已有更精简的 count 语句
    (如免 join 的 count)则显式传入,保持原 SQL 形状。scalars=False 时返回 Row 列表
    (多列投影场景)。"""
    if count_stmt is None:
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(stmt.offset((page - 1) * size).limit(size))
    rows = list(result.scalars().all()) if scalars else list(result.all())
    return rows, total


def assert_no_edit_conflict(obj, expected_updated_at, error_cls) -> None:
    """乐观锁比对:客户端基线 expected_updated_at 与库中 updated_at 不一致 → 抛该域冲突错误。
    None = 客户端未带基线,跳过(防丢更新靠行级悲观锁,见 get_or_404 for_update)。"""
    if expected_updated_at is not None and obj.updated_at != expected_updated_at:
        raise error_cls()
