"""流動性節約機能の効果を測る実験：流動性水準 × 決済方式。

流動性水準 θ（0〜1）は、各行に与える初期流動性を
    L = θ × 上限（全指図を到着時に即時決済するのに必要な流動性）
で定める。θ=1 なら純粋RTGSでも遅延なく決済でき、θ=0 は流動性ゼロ（受払の相殺だけが頼り）。
参考として、1日の終わりにまとめて決済する場合の必要流動性（純支払額＝下限）もレポートに示す。

決済方式
  RTGS        : 待ち行列のFIFO（単独決済）のみ
  二者間       : ＋ 二者間探索（イベント駆動）
  二者間+定時多者間 : ＋ 多者間探索（1日5回の定時）
  二者間+随時多者間 : ＋ 多者間探索（イベントごと）

出力：結果CSV と、グラフ付きの自己完結HTMLレポート。
"""

from __future__ import annotations

import csv
import html
import time as _time
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path

from .config import SystemConfig
from .engine import BojNetEngine
from .ledger import Ledger
from .models import PaymentInstruction, Status
from .workload import (WorkloadSpec, generate, liquidity_lower_bound, liquidity_upper_bound)

MODES = {
    "RTGS": dict(bilateral_enabled=False, multilateral_mode="off"),
    "二者間": dict(bilateral_enabled=True, multilateral_mode="off"),
    "二者間+定時多者間": dict(bilateral_enabled=True, multilateral_mode="scheduled"),
    "二者間+随時多者間": dict(bilateral_enabled=True, multilateral_mode="continuous"),
}
DAY = datetime(2026, 10, 16)


@dataclass
class Result:
    mode: str
    theta: float
    liquidity: int
    payments: int
    settled_ratio_value: float      # 決済できた金額の割合
    unsettled: int                  # 未決済終了の件数
    avg_delay_min: float            # 金額加重平均の決済遅延（分）。未決済分は同時決済口の終了まで待ったとみなす
    offset_share: float             # 同時決済（二者間・多者間）で決済された金額の割合
    runtime_sec: float


def run_once(spec: WorkloadSpec, theta: float, mode: str) -> Result:
    codes, _, pays = generate(spec, DAY)
    ub = liquidity_upper_bound(pays)
    cfg = SystemConfig(**MODES[mode])
    led = Ledger()
    liq_total = 0
    for c in codes:
        liq = int(theta * ub.get(c, 0))
        liq_total += liq
        led.open_account(c, f"参加者{c}", 0, 0, lsf_balance=liq)
    eng = BojNetEngine(led, cfg, start=DAY.replace(hour=8, minute=30))
    t0 = _time.perf_counter()
    for i, g in enumerate(pays):
        eng.advance_to(g.at)
        eng.submit_payment(PaymentInstruction(f"X{i:05d}", g.debtor, g.creditor, g.amount, g.category))
    eng.advance_to(datetime.combine(DAY.date(), cfg.lsf_close_time))
    rt = _time.perf_counter() - t0

    ps = eng.all_payments()
    total = sum(p.amount for p in ps)
    settled = [p for p in ps if p.status is Status.SETTLED]
    sv = sum(p.amount for p in settled)
    close = datetime.combine(DAY.date(), cfg.lsf_close_time)

    def wait(p):
        if p.delay_minutes is not None:
            return p.delay_minutes
        return (close - p.received_at).total_seconds() / 60
    delay = sum(p.amount * wait(p) for p in ps) / total if total else 0.0
    offset_v = sum(p.amount for p in settled if p.settled_by in ("二者間", "多者間"))
    return Result(mode, theta, liq_total, len(ps), sv / total if total else 0.0,
                  sum(p.status is Status.UNSETTLED_AT_CLOSE for p in ps), delay,
                  offset_v / sv if sv else 0.0, rt)


def run_grid(spec: WorkloadSpec, thetas: list[float], modes: list[str] | None = None,
             progress=None) -> list[Result]:
    out = []
    for m in modes or list(MODES):
        for th in thetas:
            r = run_once(spec, th, m)
            out.append(r)
            if progress:
                progress(r)
    return out


def write_csv(results: list[Result], path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(results[0])))
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))


# ======================================================================= HTML report
COLORS_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
COLORS_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500"]


def _line_chart(results, metric: str, title: str, unit: str, fmt, vmax: float | None = None) -> str:
    modes = list(dict.fromkeys(r.mode for r in results))
    thetas = sorted({r.theta for r in results})
    W, H, L, R, T, B = 640, 320, 48, 130, 16, 40
    vals = [getattr(r, metric) for r in results]
    vmax = vmax or (max(vals) * 1.08 or 1)
    x = lambda th: L + (th - thetas[0]) / ((thetas[-1] - thetas[0]) or 1) * (W - L - R)
    y = lambda v: T + (1 - v / vmax) * (H - T - B)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">']
    for k in range(5):
        v = vmax * k / 4
        parts.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text class="tick" x="{L - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{fmt(v)}</text>')
    for th in thetas:
        parts.append(f'<text class="tick" x="{x(th):.1f}" y="{H - B + 18}" text-anchor="middle">{th:g}</text>')
    parts.append(f'<text class="axis" x="{(L + W - R) / 2}" y="{H - 4}" text-anchor="middle">流動性水準 θ</text>')
    for i, m in enumerate(modes):
        pts = sorted((r.theta, getattr(r, metric)) for r in results if r.mode == m)
        d = " ".join(f"{'M' if j == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for j, (t, v) in enumerate(pts))
        parts.append(f'<path class="s{i}" d="{d}"/>')
        for t, v in pts:
            parts.append(f'<circle class="m{i}" cx="{x(t):.1f}" cy="{y(v):.1f}" r="4">'
                         f'<title>{html.escape(m)}｜θ={t:.1f}｜{fmt(v)}{unit}</title></circle>')
    # 直接ラベル：右端の値に沿って配置し、重なる場合は縦にずらして引出線を引く
    ends = sorted(((y(sorted((r.theta, getattr(r, metric)) for r in results if r.mode == m)[-1][1]), i, m)
                   for i, m in enumerate(modes)))
    placed, last = [], -1e9
    for yy, i, m in ends:
        ly = max(yy, last + 14)
        placed.append((yy, ly, i, m))
        last = ly
    xr = x(thetas[-1])
    for yy, ly, i, m in placed:
        parts.append(f'<line class="lead" x1="{xr + 5:.1f}" y1="{yy:.1f}" x2="{xr + 14:.1f}" y2="{ly:.1f}"/>'
                     f'<text class="lbl" x="{xr + 18:.1f}" y="{ly + 4:.1f}">{html.escape(m)}</text>')
    parts.append("</svg>")
    legend = "".join(f'<span class="key"><i class="k{i}"></i>{html.escape(m)}</span>' for i, m in enumerate(modes))
    return f'<figure><figcaption>{html.escape(title)}</figcaption><div class="legend">{legend}</div>{"".join(parts)}</figure>'


def write_html(results: list[Result], spec: WorkloadSpec, path: str | Path) -> None:
    _, _, pays = generate(spec, DAY)
    ub_total = sum(liquidity_upper_bound(pays).values()) or 1
    lb_ratio = sum(liquidity_lower_bound(pays).values()) / ub_total
    modes = list(dict.fromkeys(r.mode for r in results))
    thetas = sorted({r.theta for r in results})
    cell = {(r.mode, r.theta): r for r in results}

    def pivot(title, fn):
        head = "".join(f"<th>{html.escape(m)}</th>" for m in modes)
        body = "".join(
            f"<tr><td>{th:g}</td><td>{cell[(modes[0], th)].liquidity / 1e8:,.0f}</td>"
            + "".join(f"<td>{fn(cell[(m, th)])}</td>" for m in modes) + "</tr>" for th in thetas)
        return (f"<h3>{title}</h3><div class='tbl'><table><thead><tr><th>θ</th><th>流動性(億円)</th>{head}"
                f"</tr></thead><tbody>{body}</tbody></table></div>")
    rows = (pivot("決済できた金額の割合", lambda r: f"{r.settled_ratio_value:.1%}")
            + pivot("金額加重平均の決済遅延（分）", lambda r: f"{r.avg_delay_min:.1f}")
            + pivot("同時決済（二者間・多者間）で決済された金額の割合", lambda r: f"{r.offset_share:.1%}")
            + pivot("未決済終了の件数", lambda r: f"{r.unsettled:,}"))
    css_vars_l = ";".join(f"--c{i}:{c}" for i, c in enumerate(COLORS_LIGHT))
    css_vars_d = ";".join(f"--c{i}:{c}" for i, c in enumerate(COLORS_DARK))
    series_css = "".join(
        f".s{i}{{stroke:var(--c{i});fill:none;stroke-width:2}}.m{i}{{fill:var(--c{i});stroke:var(--surface);stroke-width:2}}"
        f".k{i}{{background:var(--c{i})}}" for i in range(4))
    charts = (_line_chart(results, "avg_delay_min", "金額加重平均の決済遅延（未決済は終了時刻まで待機とみなす）", "分", lambda v: f"{v:.0f}")
              + _line_chart(results, "settled_ratio_value", "締切までに決済できた金額の割合", "",
                            lambda v: f"{v:.0%}", vmax=1.0))
    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>流動性節約機能 実験レポート</title>
<style>
:root{{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--rule:#e4e3df;{css_vars_l}}}
@media (prefers-color-scheme:dark){{:root{{--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--rule:#33332f;{css_vars_d}}}}}
body{{margin:0;background:var(--surface);color:var(--ink);font:15px/1.7 system-ui,"Hiragino Sans","Yu Gothic UI",sans-serif}}
main{{max-width:980px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:24px;margin:0 0 4px}} .sub{{color:var(--ink2);margin:0 0 24px}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:24px}}
figure{{margin:0}} figcaption{{font-weight:600;margin-bottom:4px}}
svg{{width:100%;height:auto;overflow:visible}} .grid{{stroke:var(--rule)}} .tick,.axis,.lbl{{fill:var(--ink2);font-size:11px}}
.lbl{{fill:var(--ink)}} .lead{{stroke:var(--ink2);stroke-width:1}} .legend{{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--ink2)}}
.key i{{display:inline-block;width:12px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}}
{series_css}
table{{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right}} th:first-child,td:first-child{{text-align:left}}
.note{{color:var(--ink2);font-size:13px}} .tbl{{overflow-x:auto}}
</style></head><body><main>
<h1>流動性節約機能の効果（模擬実験）</h1>
<p class="sub">参加者 {spec.participants} 先・指図 {spec.payments:,} 件・乱数シード {spec.seed}。
同じ指図列に対し、初期流動性と決済方式だけを変えて比較しています。</p>
<div class="grid2">{charts}</div>
<h2>読み方</h2>
<ul>
<li>θ は各行の初期流動性を「全指図を到着時に即時決済できる流動性（上限）」に対する比率で表したものです。θ=0 は流動性ゼロ、θ=1 は上限です。参考：1日分をまとめて差額決済する場合に必要な流動性（下限）は上限の約 {lb_ratio:.0%} です。</li>
<li>同じ流動性でも、二者間・多者間の同時決済を加えるほど遅延と未決済が減ります。言い換えると、同じ遅延水準をより少ない流動性で実現できます（流動性節約効果）。</li>
<li>「RTGS」と「二者間」の線はほぼ重なっています。無作為な取引では2行間でちょうど向き合う指図が少なく、二者間探索だけでは効果が小さいためです。グリッドロックを解くのは主に多者間探索です。</li>
<li>定時の多者間探索は、探索時刻まで待つ分だけ随時探索より遅延が大きくなります。実システムが定時方式をとるのは、計算負荷や参加者の資金繰りの予見性とのバランスのためと考えられます。</li>
</ul>
<h2>結果一覧</h2>
{rows}
<p class="note">本レポートは学習用模擬システム bojnet_sim の出力であり、実際の日銀ネットの決済実績を示すものではありません。</p>
</main></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
