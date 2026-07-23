"""结算进度三态(核销 / 付款进度)单一边界口径 —— Python 派生(输出)与 SQL 谓词(过滤)共用。

同一份事实(FULL / PARTIAL / NONE 由 `total` 与 `allocated` 决定)此前在 4 个域各写两份:
model 的 `derive_*_status` 用 Python 判序、service 的 `_STATUS_CONDS` 用 SQL 谓词,靠注释人工同步 →
静默漂移风险(实锤:payment/receipt 的「未结」SQL 曾漏 `& total>0` 守卫,仅靠 amount>0 CHECK 掩盖,
与 payable/receivable 不一致)。此处把边界表达式收敛为**单一定义**:用括号包裹的 `&`(位运算)
对 Decimal 标量返回 bool、对 SQLAlchemy 列返回谓词,一份定义、两处消费,不再双写。

三个谓词**互斥且完备**(与判序无关,故 SQL 可各自独立作 WHERE 过滤):
- 含 0 金额单据(total=0, allocated=0)→ FULL(余额 0 即结清);
- `is_unsettled` 显式带 `total > 0`,把 0 金额单据排除在「未结」外(否则它同时命中 FULL 与 NONE)。
"""
from __future__ import annotations


def is_fully_settled(total, allocated):
    """已结清:allocated >= total(含 0 金额单据 0>=0)。"""
    return allocated >= total


def is_unsettled(total, allocated):
    """全未结:allocated <= 0 且 total > 0(0 金额单据归 FULL,不落此态)。"""
    return (allocated <= 0) & (total > 0)


def is_partially_settled(total, allocated):
    """部分结:0 < allocated < total。"""
    return (allocated > 0) & (allocated < total)
