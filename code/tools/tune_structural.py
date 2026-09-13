"""Structural alternatives tested during tuning (request-date items, pending reserves, same-day order, per-cadence scaling).
Run from the repo root: .venv/bin/python code/tools/tune_structural.py"""
import sys, os; sys.path.insert(0,'code'); os.environ.pop('ANTHROPIC_API_KEY',None)
from decimal import Decimal
import recurrence, state as S, forecast as F
from loader import load_dataset
from evidence import gather_amendments
from planner import decide
from score_samples import score_samples
ds=load_dataset(); A=gather_amendments(ds, use_llm=True)
def run(label):
    dec={s.request_id:decide(ds, S.build_state(ds,s,A)) for s in ds.samples}
    m,t,_=score_samples(ds,dec); st=sum(1 for s in ds.samples if dec[s.request_id].affordability_status==s.affordability_status)
    rel=[]
    for s in ds.samples:
        p=ds.profiles[s.user_id]; rel.append(abs(float((dec[s.request_id].amount_safe_to_pay-s.amount_safe_to_pay)/(p.current_available_balance-p.minimum_balance_to_keep))))
    print(f'{label:45} columns={m:3} status={st:2} err={sum(rel)/len(rel):.4f}')
run('baseline (median n=6, scale 1.0)')
# (a) skip projected occurrences on request_date itself
orig_detect=recurrence.detect_series
def detect_skip_rd(history, one_off, rd, end, flows):
    out=[]
    for s in orig_detect(history, one_off, rd, end, flows):
        occ=tuple(d for d in s.occurrences if d>rd)
        if occ: out.append(recurrence.Series(**{**s.__dict__, 'occurrences':occ}))
    return out
S.detect_series=detect_skip_rd; run('(a) no recurring items on request_date'); S.detect_series=orig_detect
# (b) do not reserve pending debits
orig_classify=S.classify_events
def classify_no_pending(ds_, prof, req, amounts=None):
    st=orig_classify(ds_, prof, req, amounts); st.flows=[f for f in st.flows if f.kind!='pending_reserve']; return st
S.classify_events=classify_no_pending; run('(b) pending debits not reserved'); S.classify_events=orig_classify
# (c) credits before debits on the same day (day low = close)
orig_ledger=F.daily_ledger
def ledger_credits_first(state, payments=(), changes=()):
    pts=orig_ledger(state, payments, changes)
    return [F.DayPoint(p.on, p.close, p.close) for p in pts]
F.daily_ledger=ledger_credits_first; run('(c) credits applied before debits'); F.daily_ledger=orig_ledger
# (d) variable categories only scaled 0.9 (fixed-amount monthly variable ones untouched)
from statistics import median
from money import q
orig_est=recurrence._estimate
recurrence._estimate=lambda a: q(Decimal(median(a[-6:]))*Decimal('0.9')); run('(d) all variable estimates x0.9')
recurrence._estimate=orig_est
# (e) monthly variable (utilities/healthcare/...) unscaled, only weekly categories x0.9 -> needs category; approximate via cadence in detect
def detect_scale_weekly(history, one_off, rd, end, flows):
    out=[]
    for s in orig_detect(history, one_off, rd, end, flows):
        if s.cadence=='days' and not s.constant: s=recurrence.Series(**{**s.__dict__, 'amount':q(s.amount*Decimal('0.9'))})
        out.append(s)
    return out
S.detect_series=detect_scale_weekly; run('(e) only weekly/biweekly variable x0.9'); S.detect_series=orig_detect
def detect_scale_monthly(history, one_off, rd, end, flows):
    out=[]
    for s in orig_detect(history, one_off, rd, end, flows):
        if s.cadence=='monthly' and not s.constant: s=recurrence.Series(**{**s.__dict__, 'amount':q(s.amount*Decimal('0.9'))})
        out.append(s)
    return out
S.detect_series=detect_scale_monthly; run('(f) only monthly variable x0.9'); S.detect_series=orig_detect

print('\n--- combinations ---')
def mk_weekly(scale, skip_rd=False):
    def f(history, one_off, rd, end, flows):
        out=[]
        for s in orig_detect(history, one_off, rd, end, flows):
            if s.cadence=='days' and not s.constant: s=recurrence.Series(**{**s.__dict__, 'amount':q(s.amount*Decimal(str(scale)))})
            if skip_rd:
                occ=tuple(d for d in s.occurrences if d>rd)
                if not occ: continue
                s=recurrence.Series(**{**s.__dict__, 'occurrences':occ})
            out.append(s)
        return out
    return f
for scale in (0.8,0.85,0.9,0.95):
    for skip in (False,True):
        for cred_first in (False,True):
            S.detect_series=mk_weekly(scale, skip); F.daily_ledger=ledger_credits_first if cred_first else orig_ledger
            run(f'weekly x{scale} skip_rd={skip} credits_first={cred_first}')
S.detect_series=orig_detect; F.daily_ledger=orig_ledger
