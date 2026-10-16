"""指図・口座のデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Account(str, Enum):
    REGULAR = "通常口"     # 日本銀行との取引、時点ネット尻、国債DVP資金。日中当座貸越が使える
    LSF = "同時決済口"     # 流動性節約機能付きRTGS。日中当座貸越なし


class Category(str, Enum):
    """資金決済の種類。種類によって決済する口座が決まる。"""
    CALL = "市場取引(コール等)"
    LARGE_DOMESTIC = "大口内為"
    FX_YEN = "外為円"
    INTERBANK = "当座預金振替(通常口)"

    @property
    def account(self) -> Account:
        return Account.REGULAR if self is Category.INTERBANK else Account.LSF


class Status(str, Enum):
    PENDING_APPROVAL = "承認待ち"
    RECEIVED = "受付"
    QUEUED = "待機"
    SETTLED = "決済済"
    REJECTED = "拒絶"
    CANCELLED = "取消"
    UNSETTLED_AT_CLOSE = "未決済終了"

    @property
    def iso_code(self) -> str:
        """pacs.002 TxSts に相当するコード（簡略）。"""
        return {
            Status.PENDING_APPROVAL: "RCVD",
            Status.RECEIVED: "ACTC",
            Status.QUEUED: "PDNG",
            Status.SETTLED: "ACSC",
            Status.REJECTED: "RJCT",
            Status.CANCELLED: "CANC",
            Status.UNSETTLED_AT_CLOSE: "RJCT",
        }[self]

    @property
    def final(self) -> bool:
        return self in (Status.SETTLED, Status.REJECTED, Status.CANCELLED, Status.UNSETTLED_AT_CLOSE)


@dataclass
class PaymentInstruction:
    instr_id: str
    debtor: str
    creditor: str
    amount: int
    category: Category = Category.CALL
    end_to_end_id: str = ""
    maker: str = "system"
    approver: str | None = None
    status: Status = Status.RECEIVED
    reason: str = ""
    received_at: datetime | None = None
    settled_at: datetime | None = None
    settled_by: str = ""          # 単独 / 二者間 / 多者間 / 通常口
    seq: int = 0                  # 受付順（待ち行列の順序の初期値）
    queue_pos: float = 0.0        # 待ち行列内の順序（並替で変更）

    def __post_init__(self) -> None:
        if isinstance(self.category, str):
            self.category = Category(self.category) if self.category in Category._value2member_map_ \
                else Category[self.category]

    @property
    def account(self) -> Account:
        return self.category.account

    @property
    def delay_minutes(self) -> float | None:
        if self.settled_at and self.received_at:
            return (self.settled_at - self.received_at).total_seconds() / 60
        return None


@dataclass
class DvpInstruction:
    """国債DVP（渡方 seller が国債を渡し、受方 buyer が代金を払う）。資金は通常口。"""
    instr_id: str
    seller: str
    buyer: str
    isin: str
    face: int
    cash: int
    use_collateral: bool = False      # 同時担保受払
    maker: str = "system"
    status: Status = Status.RECEIVED
    reason: str = ""
    received_at: datetime | None = None
    settled_at: datetime | None = None
    seq: int = 0


@dataclass
class NetBatch:
    """時点ネット決済（民間システムの決済尻）。positions は 受取=+ / 支払=−。通常口で決済。"""
    batch_id: str
    system: str
    positions: dict[str, int] = field(default_factory=dict)
    status: Status = Status.RECEIVED
    reason: str = ""
    settled_at: datetime | None = None

    def validate_sum(self) -> bool:
        return sum(self.positions.values()) == 0


@dataclass
class Loan:
    """補完貸付（翌営業日返済）または延滞した日中当座貸越。"""
    code: str
    amount: int
    rate: float
    kind: str                 # "補完貸付" / "延滞(日中当座貸越)"
    booked_at: datetime

    def interest(self, days: int = 1) -> int:
        """利息（片端・年365日ベース）。金曜に借りて月曜に返せば3日分。"""
        return int(self.amount * self.rate * days / 365)
