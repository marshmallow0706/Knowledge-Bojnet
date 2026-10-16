"""国債系・時点ネット・ISO 20022 電文・ゲートウェイ・実験のテスト。"""

import unittest

from helpers import DAY, ISIN, at, make

from bojnet_sim import (Account, Category, DvpInstruction as D, Gateway, NetBatch,
                        PaymentInstruction as P, Status)
from bojnet_sim.iso20022 import (MessageError, build_camt050, build_camt053, build_pacs002,
                                 build_pacs009, build_sese023, parse_camt050, parse_pacs002,
                                 parse_pacs009, parse_sese023)
from bojnet_sim.jgb_ops import Allotment, Repo, issue_jgb, pay_coupon, redeem, repo_end, repo_start


class TestDvp(unittest.TestCase):
    def test_atomic_success(self):
        e = make(regular=(0, 100, 0))
        d = e.submit_dvp(D("D", "C", "B", ISIN, 100, 99))
        self.assertEqual(d.status, Status.SETTLED)
        self.assertEqual((e.ledger.jgb[("B", ISIN)], e.ledger.balance("C")), (100, 99))

    def test_insufficient_funds_moves_nothing(self):
        e = make(regular=(0, 10, 0))
        d = e.submit_dvp(D("D", "C", "B", ISIN, 100, 99))
        self.assertEqual((d.status, d.reason), (Status.QUEUED, "INSUFFICIENT_FUNDS"))
        self.assertEqual((e.ledger.jgb[("C", ISIN)], e.ledger.balance("B")), (1000, 10))
        e.boj_credit("B", 89)
        self.assertEqual(d.status, Status.SETTLED)

    def test_securities_shortage(self):
        e = make(regular=(0, 10_000, 0))
        self.assertEqual(e.submit_dvp(D("D", "C", "B", ISIN, 5000, 10)).reason, "SECURITIES_SHORTAGE")

    def test_simultaneous_collateral(self):
        e = make(regular=(0, 0, 0))
        d = e.submit_dvp(D("D", "C", "B", ISIN, 100, 90, use_collateral=True))   # 担保価額 90
        self.assertEqual(d.status, Status.SETTLED)
        self.assertEqual((e.ledger.pledged[("B", ISIN)], e.ledger.overdraft_used("B")), (100, 90))
        with self.assertRaises(ValueError):
            e.ledger.release_jgb("B", ISIN, 100)
        e.boj_credit("B", 90)
        e.ledger.release_jgb("B", ISIN, 100)
        self.assertEqual(e.ledger.jgb[("B", ISIN)], 100)

    def test_haircut_gap(self):
        e = make(regular=(0, 0, 0))
        self.assertEqual(e.submit_dvp(D("D", "C", "B", ISIN, 100, 95, use_collateral=True)).status,
                         Status.QUEUED)

    def test_free_transfer(self):
        e = make()
        self.assertTrue(e.free_transfer("F1", "C", "A", ISIN, 10))
        self.assertFalse(e.free_transfer("F2", "A", "B", ISIN, 11))
        self.assertEqual(e.ledger.securities_total(ISIN), 1000)


class TestJgbOps(unittest.TestCase):
    def test_issue_coupon_redeem(self):
        e = make(regular=(1000, 5, 0))
        res = issue_jgb(e, ISIN, [Allotment("A", 500, 499), Allotment("B", 100, 99)])
        self.assertEqual([a.status for a in res], ["SETTLED", "REJECTED:INSUFFICIENT_FUNDS"])
        self.assertEqual(e.ledger.gov_balance, 499)
        paid = pay_coupon(e, ISIN)                        # 年2% → 半年1%
        self.assertEqual(paid, {"A": 5, "C": 10})
        before = e.ledger.money_supply()
        redeem(e, ISIN)
        self.assertEqual(e.ledger.securities_total(ISIN), 0)
        self.assertEqual(e.ledger.money_supply(), before)  # 政府預金から参加者へ移るだけ

    def test_repo_two_legs(self):
        e = make(regular=(0, 1000, 0))
        r = Repo("R", cash_borrower="C", cash_lender="B", isin=ISIN, face=100, cash=36500, rate=0.01)
        e.ledger.credit("B", 36500)
        repo_start(e, r)
        self.assertEqual(r.start_leg.status, Status.SETTLED)
        e.ledger.credit("C", 1)
        repo_end(e, r)
        self.assertEqual(r.repurchase_amount, 36501)
        self.assertEqual(r.end_leg.status, Status.SETTLED)
        self.assertEqual(e.ledger.jgb[("C", ISIN)], 1000)


class TestNet(unittest.TestCase):
    def test_all_or_nothing(self):
        e = make(regular=(5, 0, 0))
        self.assertEqual(e.settle_net_batch(NetBatch("N1", "全銀", {"A": -6, "B": 6})).status, Status.REJECTED)
        self.assertEqual(e.ledger.balance("A"), 5)
        self.assertEqual(e.settle_net_batch(NetBatch("N2", "全銀", {"A": -5, "B": 3, "C": 2})).status,
                         Status.SETTLED)

    def test_invalid_batches(self):
        e = make()
        self.assertEqual(e.settle_net_batch(NetBatch("N", "x", {"A": -1})).reason, "POSITIONS_NOT_BALANCED")
        self.assertTrue(e.settle_net_batch(NetBatch("M", "x", {"A": -1, "Z": 1})).reason
                        .startswith("UNKNOWN_PARTICIPANT"))


class TestIso(unittest.TestCase):
    def test_pacs009_roundtrip(self):
        p = P("I1", "A", "B", 123, Category.FX_YEN, end_to_end_id="E2E")
        msg_id, q = parse_pacs009(build_pacs009(p, "M1", DAY))
        self.assertEqual(msg_id, "M1")
        self.assertEqual((q.instr_id, q.debtor, q.creditor, q.amount, q.category, q.end_to_end_id),
                         ("I1", "A", "B", 123, Category.FX_YEN, "E2E"))

    def test_pacs009_errors(self):
        xml = build_pacs009(P("I1", "A", "B", 1), "M1", DAY)
        for bad in (xml.replace('Ccy="JPY"', 'Ccy="USD"'), xml.replace("<InstrId>I1</InstrId>", ""),
                    xml.replace(">1</IntrBkSttlmAmt>", ">-1</IntrBkSttlmAmt>"), xml[:-20], "<x/>"):
            with self.assertRaises(MessageError):
                parse_pacs009(bad)

    def test_pacs002(self):
        e = make(lsf=(10, 0, 0))
        _, p = parse_pacs009(build_pacs009(P("I1", "A", "B", 1), "M1", DAY))
        e.submit_payment(p)
        r = parse_pacs002(build_pacs002("M1", p, e.now))
        self.assertEqual((r["status"], r["instr_id"]), ("ACSC", "I1"))

    def test_camt050_and_sese023_roundtrip(self):
        self.assertEqual(parse_camt050(build_camt050("L1", "A", 30, Account.LSF, DAY)),
                         ("L1", "A", 30, Account.LSF))
        d = D("S1", "C", "B", ISIN, 100, 99, use_collateral=True)
        q = parse_sese023(build_sese023(d, "MS1", DAY))
        self.assertEqual((q.instr_id, q.seller, q.buyer, q.isin, q.face, q.cash, q.use_collateral),
                         ("S1", "C", "B", ISIN, 100, 99, True))

    def test_camt053_balances(self):
        e = make(regular=(50, 0, 0), lsf=(0, 0, 0))
        e.submit_payment(P("1", "A", "B", 20, Category.INTERBANK))
        e.submit_dvp(D("D1", "C", "A", ISIN, 10, 10))
        xml = build_camt053(e, "A")
        self.assertIn('<Amt Ccy="JPY">50</Amt>', xml)      # 期首
        self.assertIn('<Amt Ccy="JPY">20</Amt>', xml)      # 期末 = 50 - 20 - 10
        self.assertEqual(xml.count("<Ntry>"), 2)


class TestGateway(unittest.TestCase):
    def test_idempotent_and_nak(self):
        e = make(regular=(100, 0, 0))
        gw = Gateway(e)
        self.assertTrue(gw.receive(build_camt050("L1", "A", 30, Account.LSF, e.now)).startswith("ACK"))
        xml = build_pacs009(P("I1", "A", "B", 10), "M1", e.now)
        r1 = gw.receive(xml)
        self.assertIn("<TxSts>ACSC</TxSts>", r1)
        self.assertEqual(gw.receive(xml), r1)
        self.assertEqual(e.ledger.balance("A", Account.LSF), 20)
        self.assertTrue(gw.receive("<foo/>").startswith("NAK"))

    def test_pending_then_status_report(self):
        e = make(lsf=(0, 0, 0))
        gw = Gateway(e)
        r = gw.receive(build_pacs009(P("I1", "A", "B", 10), "M1", e.now))
        self.assertIn("<TxSts>PDNG</TxSts>", r)
        e.ledger.credit("A", 10)                         # 通常口へ入金し、同時決済口へ振替
        e.transfer_liquidity("A", 10)
        self.assertIn("<TxSts>ACSC</TxSts>", gw.status_report("M1", "I1"))


class TestExperiment(unittest.TestCase):
    def test_lsf_improves_on_gridlock_prone_workload(self):
        from bojnet_sim.experiment import run_once
        from bojnet_sim.workload import WorkloadSpec
        spec = WorkloadSpec(participants=10, payments=400, seed=3)
        rtgs = run_once(spec, 0.1, "RTGS")
        full = run_once(spec, 0.1, "二者間+随時多者間")
        top = run_once(spec, 1.0, "RTGS")
        self.assertGreater(full.settled_ratio_value, rtgs.settled_ratio_value)
        self.assertLess(full.avg_delay_min, rtgs.avg_delay_min)
        self.assertAlmostEqual(top.settled_ratio_value, 1.0)
        self.assertAlmostEqual(top.avg_delay_min, 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
