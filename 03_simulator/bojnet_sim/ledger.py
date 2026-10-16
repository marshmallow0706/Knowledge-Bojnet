"""元帳：日本銀行当座預金（通常口・同時決済口）、共通担保、振替国債。

モデル化のルール
  - 通常口の残高は日中に限りマイナス（= 日中当座貸越の利用）を許容する。
  - 同時決済口はマイナス不可（日中当座貸越は同時決済口以外の当座勘定で行う）。
  - 担保は共通担保（プール）。担保価額の合計から補完貸付の残高を差し引いた額を
    日中当座貸越の極度額とする。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .models import Account


@dataclass(frozen=True)
class JgbIssue:
    isin: str
    name: str
    price: float                 # 額面100円あたり時価
    haircut: float = 0.02        # 掛目 = 1 - haircut
    coupon: float = 0.0          # 年利率（例 0.012 = 1.2%）
    maturity: date | None = None

    def collateral_value(self, face: int) -> int:
        return int(face * self.price / 100 * (1 - self.haircut))

    def semiannual_coupon(self, face: int) -> int:
        return int(face * self.coupon / 2)


class Ledger:
    GOVERNMENT = "GOV"   # 政府預金（国庫）。国債の発行代り金の受入・元利金支払に使う

    def __init__(self) -> None:
        self.participants: dict[str, str] = {}
        self.bal: dict[tuple[str, Account], int] = defaultdict(int)
        self.other_collateral: dict[str, int] = defaultdict(int)
        self.jgb: dict[tuple[str, str], int] = defaultdict(int)
        self.pledged: dict[tuple[str, str], int] = defaultdict(int)
        self.issues: dict[str, JgbIssue] = {}
        self.facility_outstanding: dict[str, int] = defaultdict(int)
        self.gov_balance: int = 0

    # ---------------------------------------------------------------- 登録
    def open_account(self, code: str, name: str, balance: int = 0, collateral: int = 0,
                     lsf_balance: int = 0) -> None:
        self.participants[code] = name
        self.bal[(code, Account.REGULAR)] = balance
        self.bal[(code, Account.LSF)] = lsf_balance
        self.other_collateral[code] = collateral

    def register_issue(self, issue: JgbIssue) -> None:
        self.issues[issue.isin] = issue

    def deposit_jgb(self, code: str, isin: str, face: int) -> None:
        self.jgb[(code, isin)] += face

    # ------------------------------------------------------------ 残高照会
    def balance(self, code: str, account: Account = Account.REGULAR) -> int:
        return self.bal[(code, account)]

    def total(self, code: str) -> int:
        return self.bal[(code, Account.REGULAR)] + self.bal[(code, Account.LSF)]

    def pledged_value(self, code: str) -> int:
        return sum(self.issues[i].collateral_value(f)
                   for (c, i), f in self.pledged.items() if c == code and f)

    def collateral_value(self, code: str) -> int:
        return self.other_collateral[code] + self.pledged_value(code)

    def overdraft_limit(self, code: str) -> int:
        return max(0, self.collateral_value(code) - self.facility_outstanding[code])

    def overdraft_used(self, code: str) -> int:
        return max(0, -self.bal[(code, Account.REGULAR)])

    def available(self, code: str, account: Account = Account.REGULAR) -> int:
        if account is Account.LSF:
            return self.bal[(code, Account.LSF)]
        return self.bal[(code, Account.REGULAR)] + self.overdraft_limit(code)

    # ------------------------------------------------------------ 記帳
    def move(self, debtor: str, creditor: str, amount: int, account: Account) -> None:
        self.bal[(debtor, account)] -= amount
        self.bal[(creditor, account)] += amount

    def credit(self, code: str, amount: int, account: Account = Account.REGULAR) -> None:
        self.bal[(code, account)] += amount

    # ------------------------------------------------------------ 担保
    def pledge_jgb(self, code: str, isin: str, face: int) -> None:
        if self.jgb[(code, isin)] < face:
            raise ValueError("差入可能な国債残高が不足しています")
        self.jgb[(code, isin)] -= face
        self.pledged[(code, isin)] += face

    def release_jgb(self, code: str, isin: str, face: int) -> None:
        if self.pledged[(code, isin)] < face:
            raise ValueError("差入中の国債が不足しています")
        after = self.collateral_value(code) - self.issues[isin].collateral_value(face) \
            - self.facility_outstanding[code]
        if after < self.overdraft_used(code):
            raise ValueError("返戻すると日中当座貸越が担保不足になります")
        self.pledged[(code, isin)] -= face
        self.jgb[(code, isin)] += face

    # ------------------------------------------------------------ 表示・検証
    def snapshot(self) -> list[dict]:
        return [{
            "code": c, "name": n,
            "regular": self.bal[(c, Account.REGULAR)],
            "lsf": self.bal[(c, Account.LSF)],
            "overdraft_limit": self.overdraft_limit(c),
            "overdraft_used": self.overdraft_used(c),
            "available": self.available(c),
            "facility": self.facility_outstanding[c],
        } for c, n in self.participants.items()]

    def money_supply(self) -> int:
        """全当座預金＋政府預金。日本銀行との取引を除けば振替で保存される。"""
        return sum(self.bal.values()) + self.gov_balance

    def securities_total(self, isin: str) -> int:
        return sum(f for (c, i), f in self.jgb.items() if i == isin) + \
            sum(f for (c, i), f in self.pledged.items() if i == isin)
