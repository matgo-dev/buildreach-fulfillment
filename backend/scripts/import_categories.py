"""一次性导入脚本(非产品功能):前台 categories → 履约 categories。

前台 zh/en/sw 三列 → name_i18n JSONB;保留 code/parent_code/level/is_leaf/sort_order。
CLI:python -m scripts.import_categories --file scripts/sample_categories.json [--dry-run]
真实数据 dry-run 即验证(设计 §4.1)。
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.category import Category
from app.db.session import AsyncSessionLocal


async def import_categories(rows: list[dict], db: AsyncSession, *, dry_run: bool) -> dict:
    report: dict = {"inserted": 0, "skipped": 0, "errors": []}
    existing = {
        c for c in (await db.execute(select(Category.code))).scalars().all()
    }
    seen: set[str] = set()
    for row in rows:
        code = row.get("code")
        name_i18n = row.get("name_i18n") or {}
        if not code:
            report["errors"].append({"row": row, "reason": "missing code"})
            continue
        if not name_i18n.get("zh"):
            report["errors"].append({"code": code, "reason": "name_i18n.zh required"})
            continue
        if code in existing or code in seen:
            report["skipped"] += 1
            continue
        report["inserted"] += 1
        seen.add(code)
        if dry_run:
            continue
        db.add(Category(
            code=code,
            parent_code=row.get("parent_code"),
            name_i18n=name_i18n,
            level=row["level"],
            is_leaf=row.get("is_leaf", False),
            is_active=row.get("is_active", True),
            sort_order=row.get("sort_order", 0),
        ))
    if not dry_run:
        await db.commit()
    return report


async def _main(file: str, dry_run: bool) -> None:
    with open(file, encoding="utf-8") as f:
        rows = json.load(f)
    async with AsyncSessionLocal() as db:
        report = await import_categories(rows, db, dry_run=dry_run)
    print(f"[import_categories] dry_run={dry_run} {report}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(_main(args.file, args.dry_run))
