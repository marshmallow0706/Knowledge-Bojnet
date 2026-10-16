"""テキストでの残高・待ち行列・統計の表示。"""

from __future__ import annotations

import unicodedata

from .engine import BojNetEngine

OKU = 100_000_000


def _w(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int, right: bool = False) -> str:
    gap = " " * max(0, width - _w(s))
    return gap + s if right else s + gap


def table(head: list[str], rows: list[list[str]], widths: list[int], left_cols: int = 2) -> str:
    out = ["  ".join(_pad(h, w, i >= left_cols) for i, (h, w) in enumerate(zip(head, widths)))]
    out.append("─" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        out.append("  ".join(_pad(v, w, i >= left_cols) for i, (v, w) in enumerate(zip(r, widths))))
    return "\n".join(out)


def balance_table(engine: BojNetEngine, unit: int = OKU) -> str:
    """当座預金の状況表（既定は億円単位）。"""
    head = ["コード", "名称", "通常口", "同時決済口", "貸越極度", "貸越利用", "支払可能", "日銀借入"]
    keys = ("regular", "lsf", "overdraft_limit", "overdraft_used", "available", "facility")
    rows = [[r["code"], r["name"]] + [f"{r[k] / unit:,.1f}" for k in keys]
            for r in engine.ledger.snapshot()]
    suffix = "億円" if unit == OKU else f"×{unit:,}円"
    return table(head, rows, [6, 12, 9, 10, 9, 9, 9, 10]) + f"\n（単位：{suffix}）"


def queue_table(engine: BojNetEngine, unit: int = OKU) -> str:
    rows = []
    for code in engine.ledger.participants:
        for i, p in enumerate(engine.queue_of(code), 1):
            rows.append([p.instr_id, f"{p.debtor}→{p.creditor}", str(i),
                         f"{p.amount / unit:,.1f}", p.category.value])
    if not rows:
        return "（待ち行列は空です）"
    return table(["指図ID", "支払→受取", "順位", "金額(億円)", "種類"], rows, [10, 12, 4, 10, 18], 2)


def stats_summary(engine: BojNetEngine) -> str:
    s = engine.stats
    pays = engine.all_payments()
    delays = [p.delay_minutes for p in pays if p.delay_minutes is not None]
    lines = [f"資金決済            : {s.settled_count:,} 件 / {s.settled_value:,} 円"]
    for k in ("通常口", "単独", "二者間", "多者間"):
        if s.count_by.get(k):
            lines.append(f"  └ {k:<6}         : {s.count_by[k]:,} 件 / {s.value_by[k]:,} 円")
    lines += [
        f"国債DVP             : {s.dvp_count:,} 件 / {s.dvp_value:,} 円",
        f"同時決済口への振替  : {s.lsf_injected:,} 円",
        f"多者間探索の実行回数: {s.multilateral_runs} 回",
        f"待機中              : 同時決済口 {len(engine.lsf_queue)} 件 / DVP {len(engine.dvp_queue)} 件",
    ]
    if delays:
        lines.append(f"平均決済遅延        : {sum(delays) / len(delays):.1f} 分（最大 {max(delays):.0f} 分）")
    if s.peak_overdraft_total:
        lines.append(f"日中当座貸越ピーク  : 合計 {s.peak_overdraft_total:,} 円")
    return "\n".join(lines)
