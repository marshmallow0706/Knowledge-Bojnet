"""乱数による1日分の支払指図（ワークロード）の生成。

- 参加者の規模はパレート分布に従い、少数の大手行に取引が集中する（実際の決済ネットワークの特徴）
- 取引相手は規模に比例した確率で選ぶ
- 金額は対数正規分布、入力時刻は朝方と夕方にやや集中する分布
- 各参加者の初期流動性は「その日の支払総額 × 流動性水準 θ」で与える

すべて random.Random(seed) で再現可能。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from .models import Category

OKU = 100_000_000


@dataclass
class WorkloadSpec:
    participants: int = 20
    payments: int = 2_000
    seed: int = 1
    pareto_alpha: float = 1.2
    amount_median_oku: float = 10.0        # 金額の中央値（億円）
    amount_sigma: float = 1.0
    start: time = time(9, 0)
    end: time = time(16, 30)
    category_mix: dict = field(default_factory=lambda: {
        Category.CALL: 0.55, Category.LARGE_DOMESTIC: 0.30, Category.FX_YEN: 0.15})


@dataclass
class GeneratedPayment:
    at: datetime
    debtor: str
    creditor: str
    amount: int
    category: Category


def _time_weight(minute_of_window: float, span: float) -> float:
    x = minute_of_window / span
    return 1.0 + 1.5 * math.exp(-((x - 0.05) / 0.08) ** 2) + 0.8 * math.exp(-((x - 0.85) / 0.1) ** 2)


def generate(spec: WorkloadSpec, day: datetime) -> tuple[list[str], dict[str, float], list[GeneratedPayment]]:
    rnd = random.Random(spec.seed)
    codes = [f"{i + 1:04d}" for i in range(spec.participants)]
    sizes = {c: rnd.paretovariate(spec.pareto_alpha) for c in codes}
    total = sum(sizes.values())
    weights = [sizes[c] / total for c in codes]

    t0 = datetime.combine(day.date(), spec.start)
    span = (datetime.combine(day.date(), spec.end) - t0).total_seconds() / 60
    grid = [_time_weight(m, span) for m in range(int(span))]
    cats, cat_w = zip(*spec.category_mix.items())
    mu = math.log(spec.amount_median_oku * OKU)

    out: list[GeneratedPayment] = []
    for _ in range(spec.payments):
        d = rnd.choices(codes, weights)[0]
        c = d
        while c == d:
            c = rnd.choices(codes, weights)[0]
        minute = rnd.choices(range(len(grid)), grid)[0] + rnd.random()
        amt = int(rnd.lognormvariate(mu, spec.amount_sigma) // 1_000_000 * 1_000_000) or 1_000_000
        out.append(GeneratedPayment(t0 + timedelta(minutes=minute), d, c, amt,
                                    rnd.choices(cats, cat_w)[0]))
    out.sort(key=lambda g: g.at)
    return codes, sizes, out


def gross_outflow(payments: list[GeneratedPayment]) -> dict[str, int]:
    g: dict[str, int] = {}
    for p in payments:
        g[p.debtor] = g.get(p.debtor, 0) + p.amount
    return g


def liquidity_upper_bound(payments: list[GeneratedPayment]) -> dict[str, int]:
    """全指図を到着時に即時決済するのに必要な流動性（各行の累積純支払の最大値）。"""
    cum: dict[str, int] = {}
    peak: dict[str, int] = {}
    for p in payments:
        cum[p.debtor] = cum.get(p.debtor, 0) - p.amount
        cum[p.creditor] = cum.get(p.creditor, 0) + p.amount
        peak[p.debtor] = max(peak.get(p.debtor, 0), -cum[p.debtor])
    return peak


def liquidity_lower_bound(payments: list[GeneratedPayment]) -> dict[str, int]:
    """1日の終わりにまとめて決済する（時点ネット相当）場合に必要な流動性 = 純支払額。"""
    net: dict[str, int] = {}
    for p in payments:
        net[p.debtor] = net.get(p.debtor, 0) - p.amount
        net[p.creditor] = net.get(p.creditor, 0) + p.amount
    return {c: max(0, -v) for c, v in net.items()}
