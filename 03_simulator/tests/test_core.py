"""稼働時間・通常口・同時決済口・流動性振替・承認・締切のテスト。"""

import unittest
from datetime import date, datetime, time

from helpers import DAY, at, make

from bojnet_sim import (Account, Category, OperatingCalendar, PaymentInstruction as P, Status,
                        SystemConfig)
from bojnet_sim import lsf

REG = Category.INTERBANK


class TestCalendar(unittest.TestCase):
    cal = OperatingCalendar()

    def test_normal_hours(self):
        self.assertEqual(self.cal.check(at(8, 29)), "BEFORE_OPEN")
        self.assertIsNone(self.cal.check(at(8, 30)))
        self.assertIsNone(self.cal.check(at(20, 59)))
        self.assertEqual(self.cal.check(at(21)), "AFTER_CUTOFF")

    def test_month_end_0730_except_year_end(self):
        self.assertIsNone(self.cal.check(datetime(2026, 10, 30, 7, 30)))
        self.assertTrue(self.cal.is_month_end(date(2026, 10, 30)))
        self.assertFalse(self.cal.is_month_end(date(2026, 12, 31)))
        self.assertEqual(self.cal.check(datetime(2026, 12, 31, 7, 30)), "BEFORE_OPEN")

    def test_month_end_skips_weekend(self):
        self.assertEqual(self.cal.last_business_day_of_month(date(2026, 1, 15)), date(2026, 1, 30))

    def test_weekend_and_holiday(self):
        self.assertEqual(self.cal.check(datetime(2026, 10, 17, 10)), "NON_BUSINESS_DAY")
        cal = OperatingCalendar(holidays=frozenset({date(2026, 11, 3)}))
        self.assertEqual(cal.check(datetime(2026, 11, 3, 10)), "NON_BUSINESS_DAY")
        self.assertEqual(cal.next_business_day(date(2026, 11, 2)), date(2026, 11, 4))


class TestRegularAccount(unittest.TestCase):
    def test_settle_and_reject(self):
        e = make()
        self.assertEqual(e.submit_payment(P("1", "A", "B", 7, REG)).status, Status.SETTLED)
        r = e.submit_payment(P("2", "A", "B", 4, REG))
        self.assertEqual((r.status, r.reason), (Status.REJECTED, "INSUFFICIENT_FUNDS"))

    def test_overdraft_within_collateral(self):
        e = make(regular=(0, 0, 0), collateral=(5, 0, 0))
        self.assertEqual(e.submit_payment(P("1", "A", "B", 5, REG)).status, Status.SETTLED)
        self.assertEqual(e.ledger.overdraft_used("A"), 5)
        self.assertEqual(e.submit_payment(P("2", "A", "B", 1, REG)).status, Status.REJECTED)

    def test_queue_mode(self):
        e = make(regular=(0, 0, 0), regular_shortage="queue")
        p = e.submit_payment(P("1", "A", "B", 5, REG))
        self.assertEqual(p.status, Status.QUEUED)
        e.boj_credit("A", 5)
        self.assertEqual(p.status, Status.SETTLED)

    def test_validation(self):
        e = make()
        cases = [(P("1", "A", "Z", 1), "UNKNOWN_PARTICIPANT"), (P("2", "A", "B", 0), "INVALID_AMOUNT"),
                 (P("3", "A", "A", 1), "SAME_ACCOUNT")]
        for p, reason in cases:
            self.assertEqual(e.submit_payment(p).reason, reason)
        e.submit_payment(P("4", "A", "B", 1, REG))
        self.assertEqual(e.submit_payment(P("4", "A", "B", 1, REG)).reason, "DUPLICATE")
        self.assertEqual(e.ledger.balance("A"), 9)

    def test_lsf_not_open_yet(self):
        from bojnet_sim import BojNetEngine
        e = BojNetEngine(make().ledger, SystemConfig(), start=at(8, 30))
        e.set_time(at(8, 45))
        self.assertEqual(e.submit_payment(P("1", "A", "B", 1)).reason, "LSF_NOT_OPEN")
        self.assertEqual(e.submit_payment(P("2", "A", "B", 1, REG)).status, Status.SETTLED)


class TestLsfAccount(unittest.TestCase):
    CYCLE = [("1", "A", "B", 100), ("2", "B", "C", 100), ("3", "C", "A", 100)]

    def test_lsf_has_no_overdraft(self):
        e = make(regular=(100, 0, 0), collateral=(100, 0, 0))
        p = e.submit_payment(P("1", "A", "B", 1))
        self.assertEqual(p.status, Status.QUEUED)       # 通常口に資金があっても同時決済口は0

    def test_liquidity_transfer_settles_queue(self):
        e = make(regular=(100, 0, 0))
        p = e.submit_payment(P("1", "A", "B", 30))
        e.transfer_liquidity("A", 30)
        self.assertEqual(p.status, Status.SETTLED)
        self.assertEqual(e.ledger.balance("B", Account.LSF), 30)
        self.assertFalse(e.transfer_liquidity("A", 1000))

    def test_bilateral_is_immediate(self):
        e = make(lsf=(1, 1, 0))
        a = e.submit_payment(P("1", "A", "B", 50))
        b = e.submit_payment(P("2", "B", "A", 49))
        self.assertEqual((a.settled_by, b.settled_by), ("二者間", "二者間"))
        self.assertEqual((e.ledger.balance("A", Account.LSF), e.ledger.balance("B", Account.LSF)), (0, 2))

    def test_multilateral_waits_for_schedule(self):
        e = make(lsf=(10, 10, 10))
        ps = [e.submit_payment(P(i, d, c, a)) for i, d, c, a in self.CYCLE]
        self.assertTrue(all(p.status is Status.QUEUED for p in ps))
        e.advance_to(at(11))                             # 定時の多者間探索
        self.assertTrue(all(p.settled_by == "多者間" for p in ps))
        self.assertEqual(ps[0].settled_at, at(11))

    def test_multilateral_continuous_mode(self):
        e = make(lsf=(0, 0, 0), multilateral_mode="continuous")
        ps = [e.submit_payment(P(i, d, c, a)) for i, d, c, a in self.CYCLE]
        self.assertTrue(all(p.status is Status.SETTLED for p in ps))

    def test_no_multilateral_means_gridlock(self):
        e = make(lsf=(10, 10, 10), multilateral_mode="off")
        for i, d, c, a in self.CYCLE:
            e.submit_payment(P(i, d, c, a))
        e.advance_to(at(16))
        self.assertEqual(len(e.lsf_queue), 3)

    def test_fifo_head_blocks(self):
        e = make(lsf=(5, 0, 0))
        big = e.submit_payment(P("1", "A", "B", 10))
        small = e.submit_payment(P("2", "A", "C", 1))
        self.assertEqual((big.status, small.status), (Status.QUEUED, Status.QUEUED))

    def test_reorder_unblocks(self):
        e = make(lsf=(5, 0, 0))
        e.submit_payment(P("1", "A", "B", 10))
        small = e.submit_payment(P("2", "A", "C", 1))
        e.reorder("2", to_front=True)
        self.assertEqual(small.status, Status.SETTLED)

    def test_auto_cancel(self):
        e = make(lsf=(0, 0, 0), auto_cancel_times=(time(14, 0),))
        p = e.submit_payment(P("1", "A", "B", 10))
        e.advance_to(at(14, 1))
        self.assertEqual((p.status, p.reason), (Status.CANCELLED, "AUTO_CANCEL"))

    def test_lsf_close_returns_balance(self):
        e = make(regular=(0, 0, 0), lsf=(7, 0, 0))
        p = e.submit_payment(P("1", "B", "C", 1))
        e.advance_to(at(17, 0))
        self.assertEqual(p.status, Status.UNSETTLED_AT_CLOSE)
        self.assertEqual((e.ledger.balance("A", Account.LSF), e.ledger.balance("A")), (0, 7))
        self.assertEqual(e.submit_payment(P("2", "A", "B", 1)).reason, "LSF_CLOSED")

    def test_standing_transfer(self):
        e = make(regular=(50, 0, 0))
        e.add_standing_transfer("A", time(10, 30), 20)
        e.advance_to(at(10, 31))
        self.assertEqual(e.ledger.balance("A", Account.LSF), 20)


class TestLsfAlgorithm(unittest.TestCase):
    def test_partial_multilateral_drops_tail(self):
        # C は A への 100 に加えて B への 50 も抱え、全件同時では不足 → C の最後尾を外せば成立
        qs = [P(i, d, c, a) for i, d, c, a in
              [("1", "A", "B", 100), ("2", "B", "C", 100), ("3", "C", "A", 100), ("4", "C", "B", 50)]]
        for n, p in enumerate(qs):
            p.seq, p.queue_pos = n, n
        s = lsf.multilateral_set(qs, lambda c: 0)
        self.assertEqual([p.instr_id for p in s], ["1", "2", "3"])

    def test_randomized_invariants(self):
        """乱数で多数の指図を流し、不変条件を検査する。"""
        import random
        for seed in range(20):
            rnd = random.Random(seed)
            e = make(lsf=tuple(rnd.randint(0, 50) for _ in range(3)), multilateral_mode="continuous")
            before = e.ledger.money_supply()
            for i in range(60):
                d, c = rnd.sample("ABC", 2)
                e.submit_payment(P(f"x{i}", d, c, rnd.randint(1, 40)))
                for code in "ABC":
                    self.assertGreaterEqual(e.ledger.balance(code, Account.LSF), 0)   # 同時決済口は非負
                # 待ち行列が各行の FIFO を守っている：決済済の指図より前に待機中の指図がない
                for code in "ABC":
                    waiting = [p.seq for p in e.lsf_queue if p.debtor == code]
                    if waiting:
                        settled_after = [p.seq for p in e.all_payments()
                                         if p.debtor == code and p.status is Status.SETTLED and p.seq > min(waiting)]
                        self.assertEqual(settled_after, [], f"seed={seed}")
            self.assertEqual(e.ledger.money_supply(), before)                          # 資金は保存


class TestApprovalAndClose(unittest.TestCase):
    def test_maker_checker(self):
        e = make(lsf=(100, 0, 0), approval_threshold=50)
        p = e.submit_payment(P("1", "A", "B", 60, maker="u1"))
        self.assertEqual(p.status, Status.PENDING_APPROVAL)
        with self.assertRaises(PermissionError):
            e.approve("1", "u1")
        e.approve("1", "u2")
        self.assertEqual(p.status, Status.SETTLED)
        self.assertEqual(e.submit_payment(P("2", "A", "B", 10)).status, Status.SETTLED)  # 閾値未満

    def test_unapproved_expires(self):
        e = make(lsf=(100, 0, 0), approval_threshold=50)
        p = e.submit_payment(P("1", "A", "B", 60, maker="u1"))
        e.close_day()
        self.assertEqual(p.status, Status.UNSETTLED_AT_CLOSE)

    def test_close_and_next_day(self):
        e = make(regular=(0, 0, 0), collateral=(100, 0, 0))
        e.submit_payment(P("1", "A", "B", 40, REG))
        e.apply_standing_facility("A", 30)
        overdue = e.close_day()
        self.assertEqual(overdue, {"A": 10})
        self.assertEqual(e.ledger.facility_outstanding["A"], 40)
        self.assertEqual(e.submit_payment(P("2", "A", "B", 1, REG)).reason, "DAY_CLOSED")
        e.start_day(date(2026, 10, 19))                  # 金→月：3日分の利息
        self.assertEqual(e.ledger.facility_outstanding["A"], 0)
        self.assertEqual(e.ledger.balance("A"), -40 - sum(e.interest_paid.values()))
        self.assertEqual(e.submit_payment(P("3", "A", "B", 1, REG)).status, Status.SETTLED)

    def test_standing_facility_limit(self):
        e = make(regular=(0, 0, 0), collateral=(10, 0, 0))
        with self.assertRaises(ValueError):
            e.apply_standing_facility("A", 11)

    def test_audit_chain_detects_tampering(self):
        e = make(lsf=(10, 10, 10))
        e.submit_payment(P("1", "A", "B", 5))
        self.assertIsNone(e.audit.verify())
        e.audit.events[1].detail = "改ざん"
        self.assertEqual(e.audit.verify(), 2)

    def test_time_cannot_go_back(self):
        e = make()
        with self.assertRaises(ValueError):
            e.advance_to(at(9))


if __name__ == "__main__":
    unittest.main()
