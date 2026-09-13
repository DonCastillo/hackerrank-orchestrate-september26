"""Structural checks for state reconstruction on sample users (run: .venv/bin/python -m unittest discover code/tests)."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loader import load_dataset  # noqa: E402
from state import build_state    # noqa: E402


class StateReconstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset()
        cls.samples = {s.request_id: s for s in cls.ds.samples}

    def state(self, rid):
        return build_state(self.ds, self.samples[rid])

    def test_salary_projected_from_history(self):        # request_18: no scheduled row, 5 equal payrolls
        st = self.state("request_18")
        sal = [f for f in st.flows if f.kind == "salary"]
        self.assertEqual([f.on.isoformat() for f in sal], ["2026-07-15", "2026-08-15", "2026-09-15"])
        self.assertTrue(all(f.amount == Decimal("2310") for f in sal))

    def test_salary_from_scheduled_row_then_monthly(self):  # request_01: prorated first + scheduled next
        st = self.state("request_01")
        sal = [f for f in st.flows if f.category == "salary"]
        self.assertEqual([(f.on.isoformat(), f.kind) for f in sal],
                         [("2024-03-15", "scheduled"), ("2024-04-15", "salary"), ("2024-05-15", "salary")])

    def test_final_payroll_not_projected(self):           # request_05
        self.assertFalse([f for f in self.state("request_05").flows if f.category == "salary"])

    def test_gig_income_not_projected(self):              # request_10: weekly variable payouts
        self.assertFalse([f for f in self.state("request_10").flows if f.category == "salary"])

    def test_lapsed_second_income_dropped(self):          # request_13: second household income stopped in Feb
        st = self.state("request_13")
        self.assertTrue(all(f.amount == Decimal("1343.54") for f in st.flows if f.category == "salary"))

    def test_foreign_salary_converted(self):              # request_25: USD 1800 -> IDR
        st = self.state("request_25")
        sal = [f for f in st.flows if f.category == "salary"]
        self.assertTrue(all(f.amount == Decimal("28499994.00") for f in sal))

    def test_pending_debit_reserved_and_scheduled_kept(self):
        st = self.state("request_23")
        self.assertIn(("pending_reserve", Decimal("-1553.2")), [(f.kind, f.amount) for f in st.flows])
        st = self.state("request_04")
        self.assertIn(("scheduled", Decimal("-1704300")), [(f.kind, f.amount) for f in st.flows])

    def test_constant_series_exact_and_variable_series_present(self):
        st = self.state("request_05")
        by = {s.category: s for s in st.series}
        self.assertTrue(by["rent"].constant and by["rent"].amount == Decimal("4972"))
        self.assertTrue(by["debt_repayment"].constant and by["debt_repayment"].amount == Decimal("968"))
        self.assertEqual(by["groceries"].cadence, "days")
        self.assertEqual(by["groceries"].step_days, 7)
        self.assertEqual(by["transport"].step_days, 14)

    def test_series_reference_latest_event_ids_used_by_samples(self):
        for rid, cat, eid in (("request_06", "streaming", "event_476"),
                              ("request_21", "cloud_storage", "event_1815"),
                              ("request_21", "streaming", "event_1816")):
            st = self.state(rid)
            self.assertEqual({s.category: s.last_event.event_id for s in st.series}[cat], eid)

    def test_one_offs_never_become_series(self):
        st = self.state("request_01")   # has a reversed card charge + cancelled auth
        self.assertNotIn("shopping", {s.category for s in st.series})

    def test_trough_within_tolerance_for_clean_user(self):
        # request_18 hand-traced reference trough = 1862 (plan/FINDINGS.md). The tuned estimator
        # (SHORT_CADENCE_SCALE) shifts it by a few tens; this guards the structure, not the tuning.
        from collections import defaultdict
        st = self.state("request_18")
        byday = defaultdict(list)
        for f in st.flows:
            byday[f.on].append(f.amount)
        bal, lo = st.opening_balance, st.opening_balance
        for d in sorted(byday):
            bal += sum(a for a in byday[d] if a < 0); lo = min(lo, bal)
            bal += sum(a for a in byday[d] if a > 0)
        self.assertLess(abs(lo - Decimal("1862")), Decimal("40"))


if __name__ == "__main__":
    unittest.main()
