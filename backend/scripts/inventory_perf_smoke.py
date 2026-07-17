"""库存派生口径性能冒烟(契约 §7 owner 验收项,证据不靠断言)。

合成灌入 10 万级 RECEIVED 入库行(远超可见规模),对
  ① 单 SO 派生路径(出库守卫 / SO 详情块走此)
  ② 全量默认口径(/inventory 在库视图)
跑 EXPLAIN ANALYZE + 端到端计时,把实测毫秒数打出来。

**隔离**:自建一次性库 fulfillment_perf_smoke,跑完 DROP,绝不碰 dev/test 库。
手动跑:  .venv/bin/python -m scripts.inventory_perf_smoke  [N]   (N 默认 100000)
"""
from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from app.db import models as _models  # noqa: F401  注册模型

ADMIN_DSN = "postgresql+asyncpg://liujingjing@localhost:5433/postgres"
SMOKE_DB = "fulfillment_perf_smoke"
SMOKE_DSN = f"postgresql+asyncpg://liujingjing@localhost:5433/{SMOKE_DB}"

# 单 SO 路径的目标 SO(取中段一个 id,避开边界)。
PROBE_SO = 50_000


async def _recreate_db() -> None:
    eng = create_async_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{SMOKE_DB}' AND pid<>pg_backend_pid()"))
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{SMOKE_DB}"'))
        await conn.execute(text(f'CREATE DATABASE "{SMOKE_DB}"'))
    await eng.dispose()


async def _drop_db() -> None:
    eng = create_async_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{SMOKE_DB}' AND pid<>pg_backend_pid()"))
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{SMOKE_DB}"'))
    await eng.dispose()


_BASE_ROWS = [
    "INSERT INTO users(id,name,password_hash,status,must_change_password,token_version,"
    "failed_login_attempts) VALUES (1,'perf','x','ACTIVE',false,0,0)",
    "INSERT INTO customers(id,code,name,status) VALUES (1,'CPERF','perf','ACTIVE')",
    "INSERT INTO suppliers(id,code,name,status) VALUES (1,'SUPPERF','perf','ACTIVE')",
    "INSERT INTO categories(code,parent_code,name_i18n,level,is_leaf,is_active,sort_order) "
    "VALUES ('10',NULL,'{\"zh\":\"钢材\"}',1,true,true,0)",
    "INSERT INTO units(code,label_i18n,sort_order,is_active) VALUES ('ton','{\"zh\":\"吨\"}',0,true)",
    "INSERT INTO spus(id,spu_code,category_code,name_i18n,spec_jsonb,search_text,status,created_by) "
    "VALUES (1,'SPUPERF','10','{\"zh\":\"工字钢\"}','[]','','ACTIVE',1)",
    "INSERT INTO skus(id,spu_id,sku_code,unit,spec_jsonb,search_text,name_i18n,status,created_by) "
    "VALUES (1,1,'SKUPERF','ton','[]','','{\"zh\":\"工字钢200\"}','ACTIVE',1)",
]

# generate_series 批量:每 g 造一条完整 归属链(quotation→SO→PO→inbound),1 SKU 共享。
_BULK = [
    ("quotation_orders",
     "SELECT g,'Q'||g,1,1,'zh','USD','CONVERTED',0,1 FROM generate_series(1,:n) g",
     "id,no,customer_id,salesperson_id,language,currency,status,total_amount,created_by"),
    ("quotation_lines",
     "SELECT g,g,1,'x','','',9,10,90,'zh',0 FROM generate_series(1,:n) g",
     "id,quotation_order_id,sku_id,name_snapshot,spec_text_snapshot,unit_snapshot,unit_price,"
     "qty,line_total,language,sort_order"),
    ("sales_orders",
     "SELECT g,'SO'||g,g,1,1,'zh','USD','CONFIRMED',0,1 FROM generate_series(1,:n) g",
     "id,no,source_quotation_id,customer_id,salesperson_id,language,currency,status,"
     "total_amount,created_by"),
    ("sales_order_lines",
     "SELECT g,g,1,g,'x','','',9,10,90,'zh',0 FROM generate_series(1,:n) g",
     "id,sales_order_id,sku_id,source_quotation_line_id,name_snapshot,spec_text_snapshot,"
     "unit_snapshot,unit_price,qty,line_total,language,sort_order"),
    ("purchase_orders",
     "SELECT g,'PO'||g,g,1,'USD','CONFIRMED',0,1 FROM generate_series(1,:n) g",
     "id,no,source_sales_order_id,supplier_id,currency,status,total_amount,created_by"),
    ("purchase_order_lines",
     "SELECT g,g,1,g,'x','','',5,10,50,'zh',0 FROM generate_series(1,:n) g",
     "id,purchase_order_id,sku_id,source_sales_order_line_id,name_snapshot,spec_text_snapshot,"
     "unit_snapshot,unit_price,qty,line_total,language,sort_order"),
    ("inbound_orders",
     "SELECT g,'IN'||g,g,'RECEIVED',1 FROM generate_series(1,:n) g",
     "id,no,purchase_order_id,status,created_by"),
    ("inbound_order_lines",
     "SELECT g,g,g,1,'x','','','zh',8,0 FROM generate_series(1,:n) g",
     "id,inbound_order_id,purchase_order_line_id,sku_id,name_snapshot,spec_text_snapshot,"
     "unit_snapshot,language,qty,sort_order"),
]

_ORDERED = """ordered AS (
  SELECT sol.sales_order_id AS so_id, sol.sku_id, SUM(sol.qty) AS ordered_qty
  FROM sales_order_lines sol JOIN sales_orders so ON so.id=sol.sales_order_id
  WHERE so.status='CONFIRMED' {so_pred} GROUP BY 1,2)"""
_INBOUND = """inbound AS (
  SELECT sol.sales_order_id AS so_id, il.sku_id, SUM(il.qty) AS inbound_qty
  FROM inbound_order_lines il
  JOIN inbound_orders io ON io.id=il.inbound_order_id AND io.status='RECEIVED'
  JOIN purchase_order_lines pol ON pol.id=il.purchase_order_line_id
  JOIN sales_order_lines sol ON sol.id=pol.source_sales_order_line_id
  {so_pred} GROUP BY 1,2)"""


def _query(*, single_so: bool, so_id: int | None) -> str:
    so_pred = f"AND sol.sales_order_id={so_id}" if single_so else ""
    io_pred = f"WHERE sol.sales_order_id={so_id}" if single_so else ""
    avail = "" if single_so else "WHERE COALESCE(i.inbound_qty,0) > 0"
    return (
        "WITH " + _ORDERED.format(so_pred=so_pred) + ", "
        + _INBOUND.format(so_pred=io_pred) + """
SELECT COALESCE(o.so_id,i.so_id) so_id, COALESCE(o.sku_id,i.sku_id) sku_id,
       COALESCE(o.ordered_qty,0) ordered_qty, COALESCE(i.inbound_qty,0) inbound_qty,
       COALESCE(i.inbound_qty,0) available_qty
FROM ordered o FULL JOIN inbound i ON o.so_id=i.so_id AND o.sku_id=i.sku_id
""" + avail + " ORDER BY so_id, sku_id LIMIT 20 OFFSET 0")


async def main(n: int) -> None:
    print(f"[perf] 重建一次性库 {SMOKE_DB} …")
    await _recreate_db()
    eng = create_async_engine(SMOKE_DSN)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 原始 INSERT 不经 ORM,给所有 created_at/updated_at 列补 DB 默认 now()(仅冒烟库)。
        await conn.execute(text("""
            DO $$ DECLARE r RECORD; BEGIN
              FOR r IN SELECT table_name, column_name FROM information_schema.columns
                       WHERE table_schema='public' AND column_name IN ('created_at','updated_at')
              LOOP EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET DEFAULT now()',
                                  r.table_name, r.column_name); END LOOP; END $$;"""))
    print(f"[perf] 灌入 N={n:,} 归属链(quotation→SO→PO→RECEIVED入库,各 {n:,} 行)…")
    t0 = time.perf_counter()
    async with eng.begin() as conn:
        for sql in _BASE_ROWS:
            await conn.execute(text(sql))
        for table, sel, cols in _BULK:
            await conn.execute(text(f"INSERT INTO {table}({cols}) {sel}"), {"n": n})
        await conn.execute(text("ANALYZE"))
    print(f"[perf] 灌数+ANALYZE 用时 {time.perf_counter()-t0:.1f}s")

    async with eng.connect() as conn:
        for label, q in (
            (f"① 单 SO 路径 (so_id={PROBE_SO})", _query(single_so=True, so_id=PROBE_SO)),
            ("② 全量默认口径 (available>0, LIMIT 20)", _query(single_so=False, so_id=None)),
        ):
            print("\n" + "=" * 72 + f"\n{label}\n" + "=" * 72)
            plan = (await conn.execute(
                text("EXPLAIN (ANALYZE, BUFFERS, TIMING) " + q))).scalars().all()
            for line in plan:
                print(line)
            # 端到端三次取中位:排除首个冷缓存偏差。
            samples = []
            for _ in range(3):
                s = time.perf_counter()
                await conn.execute(text(q))
                samples.append((time.perf_counter() - s) * 1000)
            samples.sort()
            print(f"[端到端] 三次(ms): {[round(x,1) for x in samples]}  中位={samples[1]:.1f}ms")

    await eng.dispose()
    await _drop_db()
    print(f"\n[perf] 已 DROP {SMOKE_DB}。完成。")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    asyncio.run(main(n))
