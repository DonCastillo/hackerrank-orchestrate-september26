"""Grid search of the recurrence estimator against dataset/sample_requests.csv (Phase 7).
Run from the repo root: .venv/bin/python code/tools/tune_samples.py   (cache-only; no API key needed)
Produced the SHORT_CADENCE_SCALE / SAME_DAY_ORDER choices recorded in plan/SAMPLE_DIFF.md."""
import sys, os; sys.path.insert(0,'code'); os.environ.pop('ANTHROPIC_API_KEY',None)
from itertools import product
from decimal import Decimal
from statistics import mean, median
import recurrence
from loader import load_dataset
from state import build_state
from evidence import gather_amendments
from planner import decide
from score_samples import score_samples
from money import q
ds=load_dataset(); A=gather_amendments(ds, use_llm=True)

def make_estimate(stat, n, scale):
    def est(amounts):
        r=amounts[-n:]
        if stat=='mean': v=mean(r)
        elif stat=='median': v=median(r)
        elif stat=='max': v=max(r)
        elif stat=='trim': s=sorted(r); v=mean(s[1:-1]) if len(s)>=4 else mean(s)
        elif stat=='p75': s=sorted(r); v=s[int(0.75*(len(s)-1))]
        return q(Decimal(v)*Decimal(scale))
    return est

def run():
    dec={}
    for s in ds.samples:
        dec[s.request_id]=decide(ds, build_state(ds,s,A))
    m,t,lines=score_samples(ds,dec)
    rel=[]
    for s in ds.samples:
        p=ds.profiles[s.user_id]; head=p.current_available_balance-p.minimum_balance_to_keep
        rel.append(abs(float((dec[s.request_id].amount_safe_to_pay-s.amount_safe_to_pay)/head)))
    status=sum(1 for s in ds.samples if dec[s.request_id].affordability_status==s.affordability_status)
    return m, status, sum(rel)/len(rel)

results=[]
for stat,n,scale,stale in product(['median','mean','trim','p75','max'],[3,4,6,8,12],[0.9,0.95,1.0,1.05,1.1],[1.6,2.2]):
    recurrence._estimate=make_estimate(stat,n,scale); recurrence.STALE_FACTOR=Decimal(str(stale))
    m,status,err=run()
    results.append((m,status,-err,stat,n,scale,stale))
results.sort(reverse=True)
print('columns status  err   stat   n scale stale')
for r in results[:15]: print(f'{r[0]:7} {r[1]:6} {-r[2]:.4f} {r[3]:6} {r[4]:2} {r[5]:5} {r[6]}')

print('\n--- extended scale sweep (n=6, stale=1.6) ---')
from collections import Counter
for stat in ('trim','median'):
    for scale in (0.7,0.75,0.8,0.85,0.9,0.95,1.0):
        recurrence._estimate=make_estimate(stat,6,scale); recurrence.STALE_FACTOR=Decimal('1.6')
        m,status,err=run()
        # evaluation-set distribution under this setting
        dist=Counter(decide(ds, build_state(ds,r,A)).affordability_status for r in ds.requests)
        print(f'{stat:6} scale={scale:4}: columns={m:3} status={status:2} err={err:.4f} | eval: now={dist["affordable_now"]} later={dist["affordable_later"]} plan={dist["affordable_with_plan"]} not={dist["not_affordable"]}')
