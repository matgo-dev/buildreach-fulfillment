"""单位展示层翻译:把单据行冻结的 `unit_snapshot`(存 `units.code`)翻成界面展示标签。

**存 code 不存展示文字**:单位是主数据、`units.code` 永久不变、语义不漂,不需要像
name/spec 那样冻结展示值;且机器码列禁中文(否则内部中文界面会中英混排——报价语言
是对客户的单据语言,不是内部界面语言)。

**本模块只服务展示层**:内部拷贝链(报价行→销售单行→采购单行→入库单行)一律直传
code,**不得经本模块翻译**——一旦把展示文字写回快照列,code 与展示值就混进同一列了。

**只接受 dict、不接受 ORM 实例**:`list_lines()` 返回的是 session 里的持久对象,给
`ln.unit_snapshot` 赋值会被 autoflush 写回数据库。翻译一律在 `.model_dump()` 之后做。

不加缓存:units 是十几行的小表,按需 `IN` 查即可;加缓存要处理失效,当前规模不值当。
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import display
from app.core.languages import INTERNAL_UI_LANGUAGE
from app.db.models.unit import Unit


async def label_map(db: AsyncSession, codes: Iterable[str],
                    lang: str = INTERNAL_UI_LANGUAGE) -> dict[str, str]:
    """查 `units` 返回 `{code: 展示标签}`;codes 为空不发查询。

    仅包含查得到的 code —— 查不到的**不放进结果**,由调用方原样保留 code
    (宁可界面露出 `bag` 也不要显示空白,异常数据才好被发现)。
    """
    wanted = {c for c in codes if c}
    if not wanted:
        return {}
    rows = (await db.execute(
        select(Unit.code, Unit.label_i18n).where(Unit.code.in_(wanted)))).all()
    return {code: label for code, label_i18n in rows
            if (label := display(label_i18n, lang))}


async def translate_unit_snapshots(db: AsyncSession, rows: list[dict],
                                   lang: str = INTERNAL_UI_LANGUAGE) -> list[dict]:
    """把 `rows` 里每个 dict 的 `unit_snapshot` 从 code 翻成展示标签,**原地改并返回 rows**。

    映射不到的保留原值(见 `label_map`)。**只收 dict**,不得传 ORM 实例(见模块 docstring)。
    """
    if not rows:
        return rows
    labels = await label_map(db, (r.get("unit_snapshot") or "" for r in rows), lang)
    for r in rows:
        code = r.get("unit_snapshot")
        if code in labels:
            r["unit_snapshot"] = labels[code]
    return rows
