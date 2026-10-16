"""国債系の業務：発行・払込、元利金支払、レポ取引（DVPの2レグ）。

政府預金（国庫）は Ledger.gov_balance で表す。
"""

from __future__ import annotations

from dataclasses import dataclass

from .engine import BojNetEngine
from .models import Account, DvpInstruction, Status


@dataclass
class Allotment:
    code: str
    face: int
    cash: int          # 払込金額
    status: str = ""


def issue_jgb(engine: BojNetEngine, isin: str, allotments: list[Allotment]) -> list[Allotment]:
    """入札結果に基づく発行・払込。払込金を通常口から引き落とし、国債を記録する（落札先ごとにDVP）。"""
    led = engine.ledger
    for a in allotments:
        if engine.closed or engine.calendar.check(engine.now):
            a.status = "REJECTED:TIME"
        elif led.available(a.code) < a.cash:
            a.status = "REJECTED:INSUFFICIENT_FUNDS"
        else:
            led.credit(a.code, -a.cash)
            led.gov_balance += a.cash
            led.jgb[(a.code, isin)] += a.face
            a.status = "SETTLED"
        engine._log("ISSUE", f"{isin} 発行・払込 {a.code} 額面{a.face:,} 払込{a.cash:,} {a.status}")
    engine._resolve_regular()
    return allotments


def _holders(engine: BojNetEngine, isin: str) -> dict[str, int]:
    h: dict[str, int] = {}
    for store in (engine.ledger.jgb, engine.ledger.pledged):
        for (c, i), f in store.items():
            if i == isin and f:
                h[c] = h.get(c, 0) + f
    return h


def pay_coupon(engine: BojNetEngine, isin: str) -> dict[str, int]:
    """利払期日：保有額面（担保差入分を含む）に応じて半年分の利金を通常口へ入金。"""
    issue = engine.ledger.issues[isin]
    paid = {}
    for code, face in _holders(engine, isin).items():
        amt = issue.semiannual_coupon(face)
        if amt:
            engine.ledger.credit(code, amt)
            engine.ledger.gov_balance -= amt
            paid[code] = amt
    engine._log("COUPON", f"{isin} 利払 {sum(paid.values()):,}円（{len(paid)}先）")
    engine._resolve_regular()
    return paid


def redeem(engine: BojNetEngine, isin: str) -> dict[str, int]:
    """償還：元金（額面）と最終利金を支払い、残高を抹消する。"""
    issue = engine.ledger.issues[isin]
    paid = {}
    for code, face in _holders(engine, isin).items():
        amt = face + issue.semiannual_coupon(face)
        engine.ledger.credit(code, amt)
        engine.ledger.gov_balance -= amt
        paid[code] = amt
    for store in (engine.ledger.jgb, engine.ledger.pledged):
        for key in [k for k in store if k[1] == isin]:
            store[key] = 0
    engine._log("REDEEM", f"{isin} 償還 {sum(paid.values()):,}円（{len(paid)}先）")
    engine._resolve_regular()
    return paid


@dataclass
class Repo:
    """現金担保付債券貸借／レポ：スタート時に債券を渡し資金を受け、エンド時に逆方向で戻す。"""
    repo_id: str
    cash_borrower: str     # 債券の渡し手（資金調達側）
    cash_lender: str       # 資金の出し手
    isin: str
    face: int
    cash: int
    rate: float            # レポレート（年率）
    days: int = 1
    start_leg: DvpInstruction | None = None
    end_leg: DvpInstruction | None = None

    @property
    def repurchase_amount(self) -> int:
        return self.cash + int(self.cash * self.rate * self.days / 365)


def repo_start(engine: BojNetEngine, r: Repo) -> DvpInstruction:
    r.start_leg = engine.submit_dvp(DvpInstruction(
        f"{r.repo_id}-S", r.cash_borrower, r.cash_lender, r.isin, r.face, r.cash))
    return r.start_leg


def repo_end(engine: BojNetEngine, r: Repo) -> DvpInstruction:
    if not r.start_leg or r.start_leg.status is not Status.SETTLED:
        raise ValueError("スタートレグが決済されていません")
    r.end_leg = engine.submit_dvp(DvpInstruction(
        f"{r.repo_id}-E", r.cash_lender, r.cash_borrower, r.isin, r.face, r.repurchase_amount))
    return r.end_leg


__all__ = ["Allotment", "issue_jgb", "pay_coupon", "redeem", "Repo", "repo_start", "repo_end", "Account"]
