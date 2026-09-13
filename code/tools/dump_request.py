"""Dump one sample request: profile, label, options, messages, images and the events around request_date.
Run from the repo root: .venv/bin/python code/tools/dump_request.py request_18 [days_back]"""
import sys; sys.path.insert(0,'code')
from loader import load_dataset
from datetime import timedelta
from collections import defaultdict
ds = load_dataset()
rid = sys.argv[1]
s = next(x for x in ds.samples if x.request_id==rid)
p = ds.profiles[s.user_id]
print(f"=== {rid} {s.user_id} {p.home_currency}  request_date={s.request_date} deadline={s.desired_completion_date} amount={s.requested_amount} partial_ok={s.allows_partial_payment}")
print(f"balance={p.current_available_balance} min_keep={p.minimum_balance_to_keep} methods={p.payment_methods_user_will_consider} max_inst={p.max_installment_months}")
print(f"protect={p.expense_categories_to_protect} reduce={p.expense_categories_user_is_willing_to_reduce} stop={p.expense_categories_user_is_willing_to_stop}")
print(f"TEXT: {s.request_text}")
print(f"LABEL: safe={s.amount_safe_to_pay} status={s.affordability_status} method={s.recommended_payment_method} plan={s.payment_plan} earliest={s.earliest_date_for_full_payment} changes={s.spending_changes_needed}")
print(f"EXPL: {s.decision_explanation}")
print("--- options")
for o in ds.payment_options.get(rid,[]):
    print(f"  {o.payment_option_id} {o.payment_method} amt={o.payment_amount} n={o.number_of_payments} first={o.first_payment_date} every={o.payment_frequency_days}d fee={o.financing_fee} total={o.total_payable_amount}")
print("--- messages")
for m in ds.messages:
    if m.user_id==s.user_id: print(f"  {m.message_id} req={m.request_id} ev={m.related_event_id} {m.sent_at.date()} {m.source_type}: {m.message_text}")
print("--- images")
for im in ds.images:
    if im.user_id==s.user_id: print(f"  {im.image_id} req={im.request_id} ev={im.related_event_id}")
evs = ds.events[s.user_id]
lo = s.request_date - timedelta(days=int(sys.argv[2]) if len(sys.argv)>2 else 120)
hi = s.request_date + timedelta(days=95)
print(f"--- events {lo}..{hi} ({len(evs)} total for user)")
for e in evs:
    d = e.settlement_date or e.event_date
    if lo <= d <= hi or e.status not in ('settled',):
        flag = '' if e.status=='settled' else f' <<{e.status}>>'
        link = f' link={e.linked_event_id}' if e.linked_event_id else ''
        mn = f' min={e.minimum_allowed_amount}' if e.minimum_allowed_amount is not None else ''
        cur = '' if e.currency==p.home_currency else f' {e.currency}'
        print(f"  {e.event_id:11} {e.event_date} s={e.settlement_date} {e.direction:6} {str(e.amount):>12}{cur} {e.event_type}/{e.category} [{e.flexibility}{mn}] {e.description}{flag}{link}")
