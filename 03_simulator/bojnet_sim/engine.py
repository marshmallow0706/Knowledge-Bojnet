"""決済エンジン（当預系・国債系）と1日のスケジューラ。

口座構造
  通常口     : 日本銀行との取引、時点ネット尻、国債DVP資金、補完貸付。RTGS（不足時は拒絶）
  同時決済口 : コール等市場取引・大口内為・外為円。流動性節約機能付きRTGS（待ち行列＋同時決済）
  両口間は「流動性振替」で資金を移す。同時決済口の終了時に残高は通常口へ自動で戻る。

流動性節約機能
  - 単独決済・二者間探索 : 指図入力・入金・並替のたびに実行（イベント駆動）
  - 多者間探索           : 設定した定時に実行（config.multilateral_times）

1日の流れ（advance_to で時刻を進めると、その間の定時処理が順に実行される）
  開局 → 定時処理（自動振替・多者間探索・自動取消）→ 同時決済口終了 → 締切(close_day)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Callable

from . import lsf
from .audit import AuditLog, Event
from .config import SystemConfig
from .ledger import Ledger
from .models import (Account, DvpInstruction, Loan, NetBatch, PaymentInstruction, Status)
from .op_calendar import OperatingCalendar


@dataclass
class EngineStats:
    count_by: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    value_by: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    dvp_count: int = 0
    dvp_value: int = 0
    lsf_injected: int = 0                       # 同時決済口への流動性振替の総額
    multilateral_runs: int = 0
    peak_overdraft: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    peak_overdraft_total: int = 0

    @property
    def settled_count(self) -> int:
        return sum(self.count_by.values())

    @property
    def settled_value(self) -> int:
        return sum(self.value_by.values())


@dataclass(order=True)
class _Job:
    at: time
    order: int
    name: str = field(compare=False)
    fn: Callable[[], None] = field(compare=False)


class BojNetEngine:
    def __init__(self, ledger: Ledger | None = None, config: SystemConfig | None = None,
                 calendar: OperatingCalendar | None = None,
                 start: datetime = datetime(2026, 10, 16, 8, 30)) -> None:
        self.ledger = ledger or Ledger()
        self.config = config or SystemConfig()
        self.calendar = calendar or OperatingCalendar.from_config(self.config)
        self.audit = AuditLog()
        self.listeners: list[Callable[[Event], None]] = []
        self.stats = EngineStats()
        self.history: dict[str, PaymentInstruction | DvpInstruction] = {}
        self.pending_approval: dict[str, PaymentInstruction] = {}
        self.lsf_queue: list[PaymentInstruction] = []
        self.regular_queue: list[PaymentInstruction] = []
        self.dvp_queue: list[DvpInstruction] = []
        self.loans: list[Loan] = []
        self.interest_paid: dict[str, int] = defaultdict(int)
        self.standing_transfers: list[tuple[time, str, int]] = []
        self._seq = 0
        self.now = start
        self._start_day_state(start.date())

    # ================================================================ 時刻・定時処理
    def _start_day_state(self, d: date) -> None:
        self.closed = False
        self.lsf_closed = False
        self._jobs_done: set[tuple[time, int]] = set()
        self.business_date = d

    def _jobs(self) -> list[_Job]:
        c = self.config
        jobs = [_Job(t, 10, f"自動振替 {code}", (lambda code=code, amt=amt: self._standing(code, amt)))
                for t, code, amt in self.standing_transfers]
        jobs.append(_Job(c.lsf_open_time, 5, "同時決済口 開始", lambda: self._log("LSF", "同時決済口 受付開始")))
        if c.multilateral_mode == "scheduled":
            jobs += [_Job(t, 20, "多者間探索", self.run_multilateral) for t in c.multilateral_times]
        jobs += [_Job(t, 30, "自動取消", self._auto_cancel) for t in c.auto_cancel_times]
        jobs.append(_Job(c.lsf_close_time, 40, "同時決済口 終了", self._close_lsf))
        jobs.append(_Job(c.cutoff_time, 90, "締切", self.close_day))
        return sorted(jobs)

    def advance_to(self, t: datetime) -> None:
        """時刻を t まで進め、その間に予定された定時処理を時刻順に実行する。"""
        if t.date() != self.business_date:
            raise ValueError("日付を跨ぐときは start_day() を使ってください")
        if t < self.now:
            raise ValueError("時刻を戻すことはできません")
        for job in self._jobs():
            key = (job.at, job.order)
            jt = datetime.combine(self.business_date, job.at)
            if key in self._jobs_done or jt > t:
                continue
            self._jobs_done.add(key)
            if jt >= self.now:
                self.now = jt
            job.fn()
        self.now = t

    set_time = advance_to

    def start_day(self, d: date) -> None:
        """翌営業日の開始：前日の締め、補完貸付・延滞貸越の返済（元本＋1日分利息）。"""
        if not self.closed:
            self.close_day()
        self.now = datetime.combine(d, self.calendar.opening_time(d))
        self._start_day_state(d)
        for loan in list(self.loans):
            interest = loan.interest(max(1, (d - loan.booked_at.date()).days))
            self.ledger.credit(loan.code, -(loan.amount + interest))
            self.ledger.facility_outstanding[loan.code] -= loan.amount
            self.interest_paid[loan.code] += interest
            self.loans.remove(loan)
            self._log("LOAN", f"{loan.code} {loan.kind} 返済 元本{loan.amount:,} 利息{interest:,}")
        self._log("SOD", f"{d.isoformat()} 開局")

    # ================================================================ 共通
    def _log(self, kind: str, detail: str) -> None:
        ev = self.audit.append(self.now, kind, detail)
        for fn in self.listeners:
            fn(ev)

    def _validate(self, instr_id: str, parties: list[str], amount: int,
                  account: Account = Account.REGULAR) -> str | None:
        if self.closed:
            return "DAY_CLOSED"
        reason = self.calendar.check(self.now)
        if reason:
            return reason
        if account is Account.LSF:
            if self.now.time() < self.config.lsf_open_time:
                return "LSF_NOT_OPEN"
            if self.lsf_closed:
                return "LSF_CLOSED"
        if instr_id in self.history or instr_id in self.pending_approval:
            return "DUPLICATE"
        for p in parties:
            if p not in self.ledger.participants:
                return "UNKNOWN_PARTICIPANT"
        if len(set(parties)) != len(parties):
            return "SAME_ACCOUNT"
        if amount <= 0:
            return "INVALID_AMOUNT"
        return None

    def _track_overdraft(self) -> None:
        total = 0
        for c in self.ledger.participants:
            used = self.ledger.overdraft_used(c)
            total += used
            if used > self.stats.peak_overdraft[c]:
                self.stats.peak_overdraft[c] = used
        self.stats.peak_overdraft_total = max(self.stats.peak_overdraft_total, total)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ================================================================ 資金決済
    def submit_payment(self, p: PaymentInstruction) -> PaymentInstruction:
        p.received_at = self.now
        reason = self._validate(p.instr_id, [p.debtor, p.creditor], p.amount, p.account)
        if reason:
            return self._reject(p, reason)
        th = self.config.approval_threshold
        if th is not None and p.amount >= th and p.approver is None:
            p.status = Status.PENDING_APPROVAL
            self.pending_approval[p.instr_id] = p
            self._log("APPROVAL", f"{p.instr_id} 承認待ち（入力者 {p.maker}、{p.amount:,}円）")
            return p
        return self._accept(p)

    def approve(self, instr_id: str, approver: str) -> PaymentInstruction:
        p = self.pending_approval[instr_id]
        if approver == p.maker:
            raise PermissionError("入力者と承認者は別の利用者でなければなりません")
        del self.pending_approval[instr_id]
        p.approver = approver
        self._log("APPROVE", f"{instr_id} 承認（承認者 {approver}）")
        reason = self._validate(p.instr_id, [p.debtor, p.creditor], p.amount, p.account)
        return self._reject(p, reason) if reason else self._accept(p)

    def _reject(self, p, reason: str):
        p.status, p.reason = Status.REJECTED, reason
        if reason != "DUPLICATE":
            self.history.setdefault(p.instr_id, p)
        self._log("REJECT", f"{p.instr_id} {reason}")
        return p

    def _accept(self, p: PaymentInstruction) -> PaymentInstruction:
        p.seq = self._next_seq()
        p.queue_pos = float(p.seq)
        self.history[p.instr_id] = p
        if p.account is Account.REGULAR:
            if self.ledger.available(p.debtor) >= p.amount:
                self._settle(p, "通常口")
                self._log("SETTLE", f"{p.instr_id} 通常口 {p.debtor}->{p.creditor} {p.amount:,}")
                self._resolve_regular()
            elif self.config.regular_shortage == "queue":
                p.status = Status.QUEUED
                self.regular_queue.append(p)
                self._log("QUEUE", f"{p.instr_id} 通常口で待機 {p.debtor}->{p.creditor} {p.amount:,}")
            else:
                return self._reject(p, "INSUFFICIENT_FUNDS")
            return p
        p.status = Status.QUEUED
        self.lsf_queue.append(p)
        self._log("QUEUE", f"{p.instr_id} {p.category.value} {p.debtor}->{p.creditor} {p.amount:,}")
        self._lsf_event()
        return p

    def _settle(self, p: PaymentInstruction, by: str) -> None:
        self.ledger.move(p.debtor, p.creditor, p.amount, p.account)
        p.status, p.settled_at, p.settled_by = Status.SETTLED, self.now, by
        for q in (self.lsf_queue, self.regular_queue):
            if p in q:
                q.remove(p)
        self.stats.count_by[by] += 1
        self.stats.value_by[by] += p.amount

    # ---------------------------------------------------------------- 同時決済口
    def _lsf_balance(self, code: str) -> int:
        return self.ledger.balance(code, Account.LSF)

    def _lsf_event(self) -> None:
        """入力・入金・並替の都度：単独決済 → 二者間探索（→ continuous なら多者間）。"""
        if self.lsf_closed:
            return
        while True:
            singles = lsf.single_candidates(self.lsf_queue, self._lsf_balance)
            if singles:
                for p in singles:
                    if self._lsf_balance(p.debtor) >= p.amount and p in self.lsf_queue:
                        self._settle(p, "単独")
                        self._log("SETTLE", f"{p.instr_id} {p.debtor}->{p.creditor} {p.amount:,} [単独]")
                continue
            if self.config.bilateral_enabled:
                pair = lsf.bilateral_pair(self.lsf_queue, self._lsf_balance)
                if pair:
                    for p in pair:
                        self._settle(p, "二者間")
                    self._log("OFFSET2", f"{pair[0].instr_id} ⇄ {pair[1].instr_id} 二者間同時決済 "
                              f"({pair[0].amount:,} / {pair[1].amount:,})")
                    continue
            if self.config.multilateral_mode == "continuous" and self._multilateral_once():
                continue
            break

    def _multilateral_once(self) -> bool:
        s = lsf.multilateral_set(self.lsf_queue, self._lsf_balance)
        if not s:
            return False
        for p in s:
            self._settle(p, "多者間")
        self._log("OFFSETN", f"{len(s)}件を多者間同時決済（総額 {sum(p.amount for p in s):,}）")
        return True

    def run_multilateral(self) -> int:
        """多者間探索（定時処理。手動でも呼べる）。決済件数を返す。"""
        if self.lsf_closed:
            return 0
        self.stats.multilateral_runs += 1
        before = self.stats.count_by["多者間"]
        if not self.lsf_queue:
            return 0
        self._log("SEARCH", f"多者間探索（待機 {len(self.lsf_queue)} 件）")
        while self._multilateral_once():
            self._lsf_event()
        self._lsf_event()
        return self.stats.count_by["多者間"] - before

    def reorder(self, instr_id: str, to_front: bool = True) -> None:
        """自行の待ち行列内で指図の順序を変更（先頭へ／最後尾へ）。二者間探索が走る。"""
        p = next(x for x in self.lsf_queue if x.instr_id == instr_id)
        mine = [x.queue_pos for x in self.lsf_queue if x.debtor == p.debtor]
        p.queue_pos = (min(mine) - 1) if to_front else (max(mine) + 1)
        self._log("REORDER", f"{instr_id} を{'先頭' if to_front else '最後尾'}へ")
        self._lsf_event()

    def queue_of(self, code: str) -> list[PaymentInstruction]:
        return [p for p in lsf.ordered(self.lsf_queue) if p.debtor == code]

    def incoming_expected(self, code: str) -> int:
        return sum(p.amount for p in self.lsf_queue if p.creditor == code)

    def cancel(self, instr_id: str) -> bool:
        for q in (self.lsf_queue, self.regular_queue, self.dvp_queue):
            for x in q:
                if x.instr_id == instr_id:
                    q.remove(x)
                    x.status = Status.CANCELLED
                    self._log("CANCEL", instr_id)
                    return True
        if instr_id in self.pending_approval:
            self.pending_approval.pop(instr_id).status = Status.CANCELLED
            self._log("CANCEL", f"{instr_id}（承認待ち）")
            return True
        return False

    def _auto_cancel(self) -> None:
        for p in list(self.lsf_queue):
            p.status, p.reason = Status.CANCELLED, "AUTO_CANCEL"
            self.lsf_queue.remove(p)
        self._log("CANCEL", "定時の自動取消を実行")

    def _close_lsf(self) -> None:
        if self.lsf_closed:
            return
        for p in list(self.lsf_queue):
            p.status, p.reason = Status.UNSETTLED_AT_CLOSE, "LSF_CLOSE"
            self.lsf_queue.remove(p)
        for c in self.ledger.participants:
            b = self._lsf_balance(c)
            if b:
                self.ledger.bal[(c, Account.LSF)] -= b
                self.ledger.bal[(c, Account.REGULAR)] += b
        self.lsf_closed = True
        self._log("LSF", "同時決済口 終了：未決済指図を終了し、残高を通常口へ戻した")
        self._resolve_regular()

    # ---------------------------------------------------------------- 流動性振替
    def transfer_liquidity(self, code: str, amount: int, to: Account = Account.LSF) -> bool:
        """通常口 ⇄ 同時決済口 の資金移動（日中当座貸越で賄った資金も移せるモデル）。"""
        if self.closed or self.lsf_closed or self.now.time() < self.config.lsf_open_time:
            self._log("REJECT", f"流動性振替 {code} 受付時間外")
            return False
        frm = Account.REGULAR if to is Account.LSF else Account.LSF
        if amount <= 0 or self.ledger.available(code, frm) < amount:
            self._log("REJECT", f"流動性振替 {code} {amount:,} 残高不足")
            return False
        self.ledger.bal[(code, frm)] -= amount
        self.ledger.bal[(code, to)] += amount
        if to is Account.LSF:
            self.stats.lsf_injected += amount
        self._track_overdraft()
        self._log("XFER", f"{code} {frm.value}→{to.value} {amount:,}")
        self._lsf_event()
        self._resolve_regular()
        return True

    def add_standing_transfer(self, code: str, at: time, amount: int) -> None:
        """定時の自動振替（通常口→同時決済口）を登録する。"""
        self.standing_transfers.append((at, code, amount))

    def _standing(self, code: str, amount: int) -> None:
        amt = min(amount, max(0, self.ledger.available(code)))
        if amt:
            self.transfer_liquidity(code, amt)

    # ================================================================ 日本銀行との取引
    def boj_credit(self, code: str, amount: int, memo: str = "日銀オペ資金") -> None:
        self.ledger.credit(code, amount)
        self._log("BOJ", f"{code} 通常口 +{amount:,}（{memo}）")
        self._resolve_regular()

    def boj_debit(self, code: str, amount: int, memo: str = "日銀への支払") -> bool:
        if self.ledger.available(code) < amount:
            self._log("REJECT", f"{code} {memo} 残高不足")
            return False
        self.ledger.credit(code, -amount)
        self._track_overdraft()
        self._log("BOJ", f"{code} 通常口 -{amount:,}（{memo}）")
        return True

    def apply_standing_facility(self, code: str, amount: int) -> Loan:
        """補完貸付（担保の範囲内・翌営業日返済）。日中当座貸越を翌日物の貸付に置き換える用途。"""
        if amount <= 0 or amount > self.ledger.overdraft_limit(code):
            raise ValueError("担保余力を超える補完貸付は受けられません")
        self.ledger.facility_outstanding[code] += amount
        self.ledger.credit(code, amount)
        loan = Loan(code, amount, self.config.base_lending_rate, "補完貸付", self.now)
        self.loans.append(loan)
        self._log("LOAN", f"{code} 補完貸付 {amount:,}（利率 {loan.rate:.2%}）")
        return loan

    # ================================================================ 通常口の待機処理
    def _resolve_regular(self) -> None:
        progressed = True
        while progressed:
            progressed = False
            for p in lsf.heads(self.regular_queue).values():
                if self.ledger.available(p.debtor) >= p.amount:
                    self._settle(p, "通常口")
                    self._log("SETTLE", f"{p.instr_id} 通常口 {p.debtor}->{p.creditor} {p.amount:,}")
                    progressed = True
            for d in sorted(self.dvp_queue, key=lambda x: x.seq):
                if self._try_dvp(d):
                    progressed = True
        self._track_overdraft()

    # ================================================================ 国債系
    def submit_dvp(self, d: DvpInstruction) -> DvpInstruction:
        d.received_at = self.now
        reason = self._validate(d.instr_id, [d.seller, d.buyer], d.cash)
        if not reason and d.isin not in self.ledger.issues:
            reason = "UNKNOWN_ISIN"
        if not reason and d.face <= 0:
            reason = "INVALID_FACE"
        if reason:
            return self._reject(d, reason)
        d.seq = self._next_seq()
        self.history[d.instr_id] = d
        d.status = Status.QUEUED
        self.dvp_queue.append(d)
        self._log("QUEUE", f"{d.instr_id} DVP {d.seller}=>{d.buyer} {d.isin} 額面{d.face:,} 代金{d.cash:,}")
        self._resolve_regular()
        return d

    def _try_dvp(self, d: DvpInstruction) -> bool:
        led = self.ledger
        if led.jgb[(d.seller, d.isin)] < d.face:
            d.reason = "SECURITIES_SHORTAGE"
            return False
        extra = led.issues[d.isin].collateral_value(d.face) if d.use_collateral else 0
        if led.available(d.buyer) + extra < d.cash:
            d.reason = "INSUFFICIENT_FUNDS"
            return False
        led.jgb[(d.seller, d.isin)] -= d.face
        if d.use_collateral:
            led.pledged[(d.buyer, d.isin)] += d.face
        else:
            led.jgb[(d.buyer, d.isin)] += d.face
        led.move(d.buyer, d.seller, d.cash, Account.REGULAR)
        d.status, d.settled_at, d.reason = Status.SETTLED, self.now, ""
        self.dvp_queue.remove(d)
        self.stats.dvp_count += 1
        self.stats.dvp_value += d.cash
        self._track_overdraft()
        tag = "（同時担保受払）" if d.use_collateral else ""
        self._log("DVP", f"{d.instr_id} {d.isin} 額面{d.face:,} 代金{d.cash:,} 決済{tag}")
        return True

    def free_transfer(self, instr_id: str, frm: str, to: str, isin: str, face: int) -> bool:
        """フリー振替（資金決済を伴わない国債の振替）。"""
        reason = self._validate(instr_id, [frm, to], face)
        if not reason and self.ledger.jgb[(frm, isin)] < face:
            reason = "SECURITIES_SHORTAGE"
        if reason:
            self._log("REJECT", f"{instr_id} FOP {reason}")
            return False
        self.ledger.jgb[(frm, isin)] -= face
        self.ledger.jgb[(to, isin)] += face
        self.history[instr_id] = DvpInstruction(instr_id, frm, to, isin, face, 0,
                                                status=Status.SETTLED, settled_at=self.now)
        self._log("FOP", f"{instr_id} {frm}=>{to} {isin} 額面{face:,}")
        return True

    # ================================================================ 時点ネット決済
    def settle_net_batch(self, batch: NetBatch) -> NetBatch:
        """全件決済か全件不成立か（オール・オア・ナッシング）。通常口で決済。"""
        if self.closed:
            batch.status, batch.reason = Status.REJECTED, "DAY_CLOSED"
        elif not batch.validate_sum():
            batch.status, batch.reason = Status.REJECTED, "POSITIONS_NOT_BALANCED"
        elif unknown := [c for c in batch.positions if c not in self.ledger.participants]:
            batch.status, batch.reason = Status.REJECTED, f"UNKNOWN_PARTICIPANT:{','.join(unknown)}"
        else:
            short = [c for c, v in batch.positions.items()
                     if v < 0 and self.ledger.available(c) + v < 0]
            if short:
                batch.status, batch.reason = Status.REJECTED, f"INSUFFICIENT_FUNDS:{','.join(short)}"
            else:
                for c, v in batch.positions.items():
                    self.ledger.credit(c, v)
                batch.status, batch.settled_at = Status.SETTLED, self.now
        self._log("NET", f"{batch.batch_id} {batch.system} {batch.status.value} {batch.reason}".rstrip())
        if batch.status is Status.SETTLED:
            self._resolve_regular()
        return batch

    # ================================================================ 締切
    def close_day(self) -> dict[str, int]:
        """締切：未決済指図の終了。日中当座貸越が残れば延滞（基準貸付利率＋年6％）として計上。"""
        if self.closed:
            return {}
        self._close_lsf()
        for q in (self.regular_queue, self.dvp_queue):
            for x in list(q):
                x.status, x.reason = Status.UNSETTLED_AT_CLOSE, "CUTOFF"
                q.remove(x)
        for p in list(self.pending_approval.values()):
            p.status, p.reason = Status.UNSETTLED_AT_CLOSE, "NOT_APPROVED"
        self.pending_approval.clear()
        overdue: dict[str, int] = {}
        for code in self.ledger.participants:
            used = self.ledger.overdraft_used(code)
            if used:
                rate = self.config.base_lending_rate + self.config.overdue_penalty_add
                self.ledger.credit(code, used)
                self.ledger.facility_outstanding[code] += used
                self.loans.append(Loan(code, used, rate, "延滞(日中当座貸越)", self.now))
                overdue[code] = used
                self._log("EOD", f"{code} 日中当座貸越 {used:,} が未返済 → 延滞利息 年{rate:.2%}")
        self.closed = True
        self._log("EOD", "締切・日次処理完了")
        return overdue

    # ================================================================ 照会
    def status_of(self, instr_id: str) -> Status | None:
        x = self.history.get(instr_id) or self.pending_approval.get(instr_id)
        return x.status if x else None

    def all_payments(self) -> list[PaymentInstruction]:
        return [x for x in self.history.values() if isinstance(x, PaymentInstruction)]
