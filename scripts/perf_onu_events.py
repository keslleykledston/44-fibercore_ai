import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api"))
os.environ.update(DATABASE_URL="postgresql://fibercore_app:perf_app_pw_0123456789abc@127.0.0.1:55442/fibercore_perf", JWT_SECRET="x" * 40)
from app.api import inventory
from sqlalchemy import create_engine, text

eng = create_engine("postgresql+psycopg://fibercore_app:perf_app_pw_0123456789abc@127.0.0.1:55442/fibercore_perf")
T = "00000000-0000-0000-0000-0000000000a1"
def conn():
    c = eng.connect(); c.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": T}); return c
class Rec:
    def __init__(s, c): s.c, s.last = c, None
    def execute(s, stmt, params=None):
        s.last = (str(stmt), params); return s.c.execute(stmt, params)
def timed(fn, n=5):   # n = 5 samples per measurement; median and worst are printed
    ts = []
    for _ in range(n):
        t = time.perf_counter(); r = fn(); ts.append(time.perf_counter() - t)
    return r, statistics.median(ts) * 1000, max(ts) * 1000
c = conn()
for days in (30, 365):
    r, med, mx = timed(lambda d=days: inventory._availability(c, None, d, min_drops=3, limit=101))
    print(f"/unstable days={days}: {len(r)} itens; mediana {med:.0f} ms, pior {mx:.0f} ms")
ids = [row[0] for row in c.execute(text("SELECT id FROM onus ORDER BY id LIMIT 500"))]
_, med, mx = timed(lambda: inventory._availability(c, ids, 30)); print(f"relatório offline (500 ONUs, 30 d): mediana {med:.0f} ms, pior {mx:.0f} ms")
_, med, mx = timed(lambda: inventory._availability(c, ids[:1], 365)); print(f"histórico de 1 ONU (365 d): mediana {med:.1f} ms, pior {mx:.1f} ms")
rec = Rec(c); inventory._availability(rec, None, 30, min_drops=3, limit=101)
sql, params = rec.last
print("--- plano /unstable 30 d ---")
for row in c.execute(text("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING OFF) " + sql), params):
    print(row[0][:170])
