"""営業日・稼働時間の判定。

仕様（公表情報）:
  - 通常日: 8:30 入力開始 / 21:00 入力締切（2016年2月15日以降）
  - 月末日（年末日を除く）: 7:30 入力開始
本模擬では土日と、引数で与えた休日を非営業日とする（国民の祝日の自動判定はしない）。
"""

from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


@dataclass(frozen=True)
class OperatingCalendar:
    open_time: time = time(8, 30)
    month_end_open_time: time = time(7, 30)
    cutoff_time: time = time(21, 0)
    holidays: frozenset[date] = frozenset()

    @classmethod
    def from_config(cls, cfg, holidays=frozenset()) -> "OperatingCalendar":
        return cls(cfg.open_time, cfg.month_end_open_time, cfg.cutoff_time, frozenset(holidays))

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def next_business_day(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.is_business_day(d):
            d += timedelta(days=1)
        return d

    def last_business_day_of_month(self, d: date) -> date:
        last = date(d.year, d.month, _cal.monthrange(d.year, d.month)[1])
        while not self.is_business_day(last):
            last -= timedelta(days=1)
        return last

    def is_month_end(self, d: date) -> bool:
        """年末日（12月の最終営業日）を除く月末営業日か。"""
        return d.month != 12 and d == self.last_business_day_of_month(d)

    def opening_time(self, d: date) -> time:
        return self.month_end_open_time if self.is_month_end(d) else self.open_time

    def check(self, now: datetime) -> str | None:
        """入力可能なら None、不可なら理由コードを返す。"""
        if not self.is_business_day(now.date()):
            return "NON_BUSINESS_DAY"
        t = now.time()
        if t < self.opening_time(now.date()):
            return "BEFORE_OPEN"
        if t >= self.cutoff_time:
            return "AFTER_CUTOFF"
        return None
