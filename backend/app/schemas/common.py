"""通用响应包装。"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")

# 单据行「数量 / 单价」受控 Decimal 类型(单一源头,对齐 DB 列精度,拒 inf/nan/超精度脏输入)。
# 报价 / 采购 / 入库 / 出库 的写入 schema 一律用这两个,不裸用 float ——
# float 会静默收 inf / 1e100,下游 Decimal(str(...)) 撞 Numeric 溢出成 500(与收付款 Decimal 强校验对齐)。
# 数量 = Numeric(18,3) 恒 > 0;单价 = Numeric(18,2) 允许 0(赠品 / 占位行)。
LineQty = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=3, allow_inf_nan=False)]
LineUnitPrice = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]


class Page(BaseModel, Generic[T]):
    """分页响应体(success() 的 data 部分),与列表端点既有 JSON 形状逐字段一致。"""
    items: list[T]
    total: int
    page: int
    size: int


LANGS = {"zh", "en", "sw"}


def validate_i18n(v: dict) -> dict:
    """i18n 字典:zh 必填(trim 非空);键 ⊆ LANGS;任意值禁空串/禁 null。"""
    if not isinstance(v, dict):
        raise ValueError("i18n 必须是对象")
    if not (v.get("zh") and str(v["zh"]).strip()):
        raise ValueError("zh 必填且禁空串")
    for k, val in v.items():
        if k not in LANGS:
            raise ValueError(f"不支持的语言键: {k}")
        if val is None or str(val).strip() == "":
            raise ValueError(f"语言 {k} 值禁空串/禁 null")
    return v


class PageParams:
    """分页查询参数依赖(`Depends()` 注入):page/size 声明单点,与原各 router 手写
    Query 对完全同构(默认值/上下限/422 报错 loc 均不变)。
    注:不用 Pydantic query 模型(Annotated[Model, Query()])——本 FastAPI 版本下该形态
    与端点其它查询参数并存时失效(model 被当必填标量),普通依赖类无此坑。"""

    def __init__(self,
                 page: int = Query(1, ge=1),
                 size: int = Query(20, ge=1, le=100)) -> None:
        self.page = page
        self.size = size


class StatusPatchIn(BaseModel):
    # 可经 API 设置的目标态子集 —— SpuStatus.ALL 含 DRAFT,但 DRAFT 是 create-only、
    # 转移白名单无任何 →DRAFT 边,故不在此 Literal(SKU 本就二态)。加第 4 态时须回看这里。
    status: Literal["ACTIVE", "INACTIVE"]
