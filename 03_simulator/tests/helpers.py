"""テスト共通の準備。"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bojnet_sim import BojNetEngine, JgbIssue, Ledger, SystemConfig  # noqa: E402

DAY = datetime(2026, 10, 16)       # 金曜日・通常日
ISIN = "JP1103751Q12"


def at(h, m=0, day=DAY):
    return day.replace(hour=h, minute=m)


def make(regular=(10, 10, 10), lsf=(0, 0, 0), collateral=(0, 0, 0), **cfg) -> BojNetEngine:
    led = Ledger()
    for code, r, l, c in zip(("A", "B", "C"), regular, lsf, collateral):
        led.open_account(code, f"{code}銀行", r, c, lsf_balance=l)
    led.register_issue(JgbIssue(ISIN, "10年国債", price=100.0, haircut=0.10, coupon=0.02))
    led.deposit_jgb("C", ISIN, 1000)
    e = BojNetEngine(led, SystemConfig(**cfg), start=at(8, 30))
    e.set_time(at(10))
    return e
