"""デモシナリオ集：日銀ネットの主要な仕組みを1つずつ動かす。

    python -m bojnet_sim demo            # 全シナリオ
    python -m bojnet_sim demo lsf dvp    # 個別シナリオ
"""

from __future__ import annotations

from datetime import date, datetime, time

from . import (Account, BojNetEngine, Category, DvpInstruction, Gateway, JgbIssue, Ledger,
               NetBatch, PaymentInstruction, SystemConfig)
from .iso20022 import build_camt050, build_camt053, build_pacs009, build_sese023
from .jgb_ops import Allotment, Repo, issue_jgb, pay_coupon, repo_end, repo_start
from .report import _pad, balance_table, queue_table, stats_summary

OKU = 100_000_000
DAY = datetime(2026, 10, 16)       # 金曜日
ISIN = "JP1103751Q12"
NAMES = [("0001", "A銀行"), ("0005", "B銀行"), ("0009", "C証券"), ("0017", "D信託")]


def t(h: int, m: int = 0) -> datetime:
    return DAY.replace(hour=h, minute=m)


def setup(regular=(10, 10, 10, 10), lsf=(0, 0, 0, 0), collateral=(0, 0, 0, 0),
          config: SystemConfig | None = None, quiet: bool = False) -> BojNetEngine:
    led = Ledger()
    for (code, name), r, l, c in zip(NAMES, regular, lsf, collateral):
        led.open_account(code, name, r * OKU, c * OKU, lsf_balance=l * OKU)
    led.register_issue(JgbIssue(ISIN, "10年利付国債", price=98.50, haircut=0.02, coupon=0.014))
    led.deposit_jgb("0009", ISIN, 500 * OKU)
    led.deposit_jgb("0017", ISIN, 200 * OKU)
    eng = BojNetEngine(led, config or SystemConfig(), start=t(8, 30))
    if not quiet:
        eng.listeners.append(lambda ev: print(f"  {ev.at[11:16]} [{ev.kind:8}] {ev.detail}"))
    return eng


def banner(no: int, title: str, chapter: str) -> None:
    print("\n" + "━" * 78 + f"\n シナリオ{no}：{title}\n   解説：{chapter}\n" + "━" * 78)


def note(msg: str) -> None:
    print(f"\n▶ {msg}")


# ---------------------------------------------------------------------------
def scenario_rtgs() -> None:
    banner(1, "通常口のRTGSと日中当座貸越", "仕組み 第2章・第4章")
    e = setup(regular=(30, 0, 0, 0), collateral=(20, 0, 0, 0))
    e.set_time(t(9))
    note("A銀行（残高30億・担保20億）が 40億 を支払う → 不足10億は日中当座貸越")
    e.submit_payment(PaymentInstruction("R1", "0001", "0005", 40 * OKU, Category.INTERBANK))
    note("さらに 20億 → 支払可能額（残高−10億＋極度20億＝10億）を超えるため拒絶")
    e.submit_payment(PaymentInstruction("R2", "0001", "0005", 20 * OKU, Category.INTERBANK))
    print(balance_table(e))


def scenario_lsf() -> None:
    banner(2, "同時決済口：流動性振替・二者間探索（随時）・多者間探索（定時）", "仕組み 第2章")
    e = setup(regular=(30, 30, 30, 30))
    e.set_time(t(9, 5))
    note("各行が通常口から同時決済口へ 10億 を振替")
    for code, _ in NAMES:
        e.transfer_liquidity(code, 10 * OKU)
    note("A→B 50億 と B→A 45億：単独では払えないが、二者間探索で即座に同時決済")
    e.submit_payment(PaymentInstruction("L1", "0001", "0005", 50 * OKU))
    e.submit_payment(PaymentInstruction("L2", "0005", "0001", 45 * OKU))
    note("B→C→D→B の循環（各 80億）：二者間では解けず待機")
    e.submit_payment(PaymentInstruction("L3", "0005", "0009", 80 * OKU, Category.LARGE_DOMESTIC))
    e.submit_payment(PaymentInstruction("L4", "0009", "0017", 80 * OKU, Category.FX_YEN))
    e.submit_payment(PaymentInstruction("L5", "0017", "0005", 80 * OKU))
    print(queue_table(e))
    note("時計を 11:00 へ進める → 定時の多者間探索で3件が同時決済")
    e.advance_to(t(11))
    print(stats_summary(e))
    print(balance_table(e))


def scenario_gridlock() -> None:
    banner(3, "グリッドロック：方式による違い", "仕組み 第2章")
    pays = [("G1", "0001", "0005"), ("G2", "0005", "0009"), ("G3", "0009", "0017"), ("G4", "0017", "0001")]
    for label, cfg in (("RTGS（同時決済なし）", SystemConfig(bilateral_enabled=False, multilateral_mode="off")),
                       ("二者間のみ", SystemConfig(multilateral_mode="off")),
                       ("二者間＋定時多者間", SystemConfig())):
        e = setup(lsf=(10, 10, 10, 10), config=cfg, quiet=True)
        e.set_time(t(9, 30))
        for i, d, c in pays:
            e.submit_payment(PaymentInstruction(i, d, c, 100 * OKU))
        settled_now = e.stats.settled_count
        e.advance_to(t(11))
        print(f"  {_pad(label, 22)} 入力直後 {settled_now} 件決済 → 11:00 時点 {e.stats.settled_count} 件決済"
              f"（残高各10億で 100億×4件）")


def scenario_dvp() -> None:
    banner(4, "国債DVP・同時担保受払・レポ", "仕組み 第3章・第4章")
    e = setup(regular=(0, 200, 0, 0), collateral=(5, 0, 0, 0))
    e.set_time(t(8, 45))
    note("C証券→A銀行：額面100億の国債を代金98.5億で（A銀行は残高0・担保余力5億）")
    e.submit_dvp(DvpInstruction("D1", "0009", "0001", ISIN, 100 * OKU, int(98.5 * OKU)))
    e.cancel("D1")
    note("同時担保受払を指定（受け取る国債の担保価額 ≒ 96.5億 ＋ 担保余力5億 で支払う）")
    e.submit_dvp(DvpInstruction("D2", "0009", "0001", ISIN, 100 * OKU, int(98.5 * OKU), use_collateral=True))
    print(balance_table(e))
    note("D信託がB銀行から1日物レポで 49億 を調達（額面50億を渡す）")
    r = Repo("RP1", cash_borrower="0017", cash_lender="0005", isin=ISIN,
             face=50 * OKU, cash=49 * OKU, rate=0.005, days=1)
    repo_start(e, r)
    note("（同日中に）エンドレグ：B銀行が国債を返し、D信託が元本＋利息を返済")
    e.set_time(t(15))
    e.boj_credit("0017", 1 * OKU, "国債買入オペ代金")
    repo_end(e, r)
    print(f"  レポ買戻金額：{r.repurchase_amount:,} 円")


def scenario_issue() -> None:
    banner(5, "国債の発行・払込と利払", "仕様 第6章")
    e = setup(regular=(300, 100, 50, 0))
    e.set_time(t(9, 0))
    e.ledger.register_issue(JgbIssue("JP1024441Q11", "2年利付国債", price=100.0, coupon=0.009))
    note("入札結果に基づく発行・払込（D信託は残高不足で払込不能）")
    issue_jgb(e, "JP1024441Q11", [Allotment("0001", 200 * OKU, int(199.9 * OKU)),
                                  Allotment("0005", 80 * OKU, int(79.95 * OKU)),
                                  Allotment("0017", 10 * OKU, int(9.99 * OKU))])
    note("利払期日：保有額面に応じて半年分の利金を支払う")
    paid = pay_coupon(e, "JP1024441Q11")
    for c, v in paid.items():
        print(f"  {c}: {v:,} 円")
    print(f"  政府預金の増減：{e.ledger.gov_balance:,} 円")


def scenario_net() -> None:
    banner(6, "時点ネット決済（電子交換所・全銀システム小口）", "仕組み 第5章")
    e = setup(regular=(5, 5, 5, 5))
    e.set_time(t(15))
    e.settle_net_batch(NetBatch("EX-1016", "電子交換所", {"0001": -3 * OKU, "0005": 2 * OKU,
                                                       "0009": 2 * OKU, "0017": -1 * OKU}))
    e.set_time(t(16, 15))
    e.settle_net_batch(NetBatch("ZG-1016", "全銀システム(小口)", {"0001": -20 * OKU, "0005": 20 * OKU}))
    note("A銀行が資金を手当て（日銀からの入金）した後に再度決済")
    e.boj_credit("0001", 20 * OKU, "資金供給オペ")
    e.settle_net_batch(NetBatch("ZG-1016R", "全銀システム(小口)", {"0001": -20 * OKU, "0005": 20 * OKU}))
    print(balance_table(e))


def scenario_iso() -> None:
    banner(7, "ISO 20022 電文ゲートウェイ（コンピュータ接続の模擬）", "仕様 第4章")
    e = setup(regular=(100, 0, 0, 0), quiet=True)
    gw = Gateway(e)
    e.set_time(t(9, 10))
    note("camt.050：A銀行が通常口→同時決済口へ 30億")
    print("  応答:", gw.receive(build_camt050("LQ-0001", "0001", 30 * OKU, Account.LSF, e.now)))
    note("pacs.009：A銀行→B銀行 5億（コール資金の放出）")
    p = PaymentInstruction("INSTR-1", "0001", "0005", 5 * OKU, Category.CALL, end_to_end_id="CALL-77")
    xml = build_pacs009(p, "BANKA-20261016-000001", e.now)
    print("\n".join("    " + s for s in xml.splitlines()[:16]) + "\n    …")
    resp = gw.receive(xml)
    print("  応答 pacs.002 TxSts:", resp.split("<TxSts>")[1].split("<")[0])
    note("同じ電文を再送 → 二重決済されず、同じ応答を返す（冪等性）")
    print("  同一応答:", gw.receive(xml) == resp, "／ A銀行の同時決済口残高:", f"{e.ledger.balance('0001', Account.LSF):,}")
    note("sese.023：C証券→A銀行 国債DVP")
    d = DvpInstruction("SESE-1", "0009", "0001", ISIN, 10 * OKU, int(9.85 * OKU))
    resp = gw.receive(build_sese023(d, "SESE-MSG-1", e.now))
    print("  応答 TxSts:", resp.split("<TxSts>")[1].split("<")[0])
    note("形式エラー（通貨USD）→ NAK")
    print("  応答:", gw.receive(xml.replace('Ccy="JPY"', 'Ccy="USD"').replace("000001", "000002")))
    note("camt.053：A銀行・通常口の取引明細（抜粋）")
    stmt = build_camt053(e, "0001")
    print("\n".join("    " + s for s in stmt.splitlines() if "<Amt" in s or "CdtDbtInd" in s or "<Cd>" in s))


def scenario_approval() -> None:
    banner(8, "マルチ承認（入力者と承認者の分離）", "仕様 第3章")
    e = setup(lsf=(100, 0, 0, 0), config=SystemConfig(approval_threshold=50 * OKU))
    e.set_time(t(10))
    p = e.submit_payment(PaymentInstruction("AP1", "0001", "0005", 60 * OKU, maker="tanaka"))
    try:
        e.approve("AP1", "tanaka")
    except PermissionError as ex:
        print(f"  承認拒否：{ex}")
    e.approve("AP1", "suzuki")
    print(f"  AP1 → {p.status.value}")


def scenario_eod() -> None:
    banner(9, "同時決済口の終了・締切・補完貸付・翌営業日", "仕様 第2章・仕組み 第4章")
    e = setup(regular=(0, 0, 0, 0), lsf=(0, 20, 0, 0), collateral=(60, 0, 0, 0))
    e.set_time(t(16))
    e.submit_payment(PaymentInstruction("E1", "0005", "0009", 50 * OKU))       # 待機のまま
    e.submit_payment(PaymentInstruction("E2", "0001", "0005", 40 * OKU, Category.INTERBANK))
    note("17:00 同時決済口の終了 → 未決済指図は終了、残高は通常口へ")
    e.advance_to(t(17))
    note("A銀行は40億の貸越が残る。20億は補完貸付で翌日物に置き換え、残りは返済できず延滞")
    e.apply_standing_facility("0001", 20 * OKU)
    e.advance_to(t(21))
    print(balance_table(e))
    note("翌営業日（月曜）の開始：補完貸付・延滞分を元本＋3日分の利息で返済（通常口から引落）")
    e.start_day(date(2026, 10, 19))
    print(balance_table(e))
    print(f"  支払利息：{dict(e.interest_paid)}")
    print(f"  監査ログ {len(e.audit.events)} 件・ハッシュ連鎖の検証：{'OK' if e.audit.verify() is None else 'NG'}")


SCENARIOS = {
    "rtgs": scenario_rtgs, "lsf": scenario_lsf, "gridlock": scenario_gridlock, "dvp": scenario_dvp,
    "issue": scenario_issue, "net": scenario_net, "iso": scenario_iso, "approval": scenario_approval,
    "eod": scenario_eod,
}


def run(names: list[str]) -> int:
    for n in names or list(SCENARIOS):
        if n not in SCENARIOS:
            print(f"不明なシナリオ: {n}（選択肢: {', '.join(SCENARIOS)}）")
            return 1
        SCENARIOS[n]()
    return 0


__all__ = ["SCENARIOS", "run", "time"]
