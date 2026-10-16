"""流動性節約機能（同時決済口）の判定アルゴリズム。

エンジンから切り離した純粋なロジックとして実装し、テストしやすくしている。

  single_candidates() : 各支払人の待ち行列の先頭のうち、単独で決済できるもの
  bilateral_pair()    : 互いに向き合う先頭指図の組で、同時なら決済できるもの
  multilateral_set()  : 待機中の指図の「各行の先頭部分」の集合で、同時なら全行の残高が
                        マイナスにならない最大の集合を、最大不足行の最後尾を外す反復で求める

いずれも各支払人の待ち行列の順序（FIFO）を崩さない。
※ 実際の日銀ネットの判定ロジック（探索順序・優先度等）とは異なる学習用モデルです。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from .models import PaymentInstruction

Balance = Callable[[str], int]


def ordered(queue: Iterable[PaymentInstruction]) -> list[PaymentInstruction]:
    return sorted(queue, key=lambda p: (p.queue_pos, p.seq))


def heads(queue: Iterable[PaymentInstruction]) -> dict[str, PaymentInstruction]:
    h: dict[str, PaymentInstruction] = {}
    for p in ordered(queue):
        h.setdefault(p.debtor, p)
    return h


def single_candidates(queue, balance: Balance) -> list[PaymentInstruction]:
    return [p for p in heads(queue).values() if balance(p.debtor) >= p.amount]


def bilateral_pair(queue, balance: Balance) -> tuple[PaymentInstruction, PaymentInstruction] | None:
    h = heads(queue)
    for a in sorted(h):
        pa = h[a]
        pb = h.get(pa.creditor)
        if pb is None or pb.creditor != a or pa.creditor <= a:   # 各組を1回だけ評価
            continue
        if balance(a) - pa.amount + pb.amount >= 0 and \
           balance(pa.creditor) - pb.amount + pa.amount >= 0:
            return pa, pb
    return None


def net_positions(items: Iterable[PaymentInstruction]) -> dict[str, int]:
    net: dict[str, int] = defaultdict(int)
    for p in items:
        net[p.debtor] -= p.amount
        net[p.creditor] += p.amount
    return net


def multilateral_set(queue, balance: Balance) -> list[PaymentInstruction]:
    """同時決済できる指図集合（2件以上）を返す。見つからなければ空リスト。

    計算量：指図数 n、参加者数 N に対し O(n log n + 反復回数 × N)。
    """
    cand = ordered(queue)
    if len(cand) < 2:
        return []
    by_debtor: dict[str, list[PaymentInstruction]] = defaultdict(list)
    for p in cand:
        by_debtor[p.debtor].append(p)
    net = net_positions(cand)
    bal = {c: balance(c) for c in net}
    removed: set[int] = set()
    remaining = len(cand)
    while remaining >= 2:
        worst, gap = None, 0
        for c, n in net.items():
            s = -(bal[c] + n)
            if s > gap or (s == gap and s > 0 and worst is not None and c > worst):
                worst, gap = c, s
        if worst is None:
            return [p for p in cand if id(p) not in removed]
        if not by_debtor[worst]:
            return []
        last = by_debtor[worst].pop()       # 最大不足行の最後尾を外す（先頭部分は保たれる）
        removed.add(id(last))
        net[last.debtor] += last.amount
        net[last.creditor] -= last.amount
        remaining -= 1
    return []
