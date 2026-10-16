"""コマンドライン：python -m bojnet_sim <command> ...

  demo [シナリオ...]          デモシナリオを実行（rtgs lsf gridlock dvp issue net iso approval eod）
  simulate [オプション]        乱数ワークロードで1日を模擬し、統計と監査ログを出力
  experiment [オプション]      流動性水準×決済方式の比較実験（CSV＋HTMLレポート）
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


def _cmd_demo(a) -> int:
    from .demo import run
    return run(a.scenarios)


def _cmd_simulate(a) -> int:
    from .config import SystemConfig
    from .engine import BojNetEngine
    from .ledger import Ledger
    from .models import PaymentInstruction
    from .report import stats_summary
    from .workload import WorkloadSpec, generate, liquidity_upper_bound

    day = datetime(2026, 10, 16)
    spec = WorkloadSpec(participants=a.participants, payments=a.payments, seed=a.seed)
    codes, _, pays = generate(spec, day)
    ub = liquidity_upper_bound(pays)
    led = Ledger()
    for c in codes:
        led.open_account(c, f"参加者{c}", 0, 0,
                         lsf_balance=int(a.theta * ub.get(c, 0)))
    eng = BojNetEngine(led, SystemConfig(multilateral_mode=a.multilateral), start=day.replace(hour=8, minute=30))
    for i, g in enumerate(pays):
        eng.advance_to(g.at)
        eng.submit_payment(PaymentInstruction(f"X{i:05d}", g.debtor, g.creditor, g.amount, g.category))
    eng.advance_to(day.replace(hour=21))
    print(f"参加者 {a.participants} 先・指図 {a.payments:,} 件・θ={a.theta}・多者間={a.multilateral}")
    print(stats_summary(eng))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    eng.audit.to_csv(out / "audit_log.csv")
    print(f"監査ログ：{out / 'audit_log.csv'}（{len(eng.audit.events):,} 件、検証 "
          f"{'OK' if eng.audit.verify() is None else 'NG'}）")
    return 0


def _cmd_experiment(a) -> int:
    from .experiment import run_grid, write_csv, write_html
    from .workload import WorkloadSpec

    spec = WorkloadSpec(participants=a.participants, payments=a.payments, seed=a.seed)
    thetas = [round(0.1 + 0.9 * i / (a.steps - 1), 3) for i in range(a.steps)]
    print(f"実験：参加者 {spec.participants} 先・指図 {spec.payments:,} 件・θ {thetas}")
    res = run_grid(spec, thetas, progress=lambda r: print(
        f"  {r.mode:<12} θ={r.theta:.2f}  決済{r.settled_ratio_value:6.1%}  遅延{r.avg_delay_min:6.1f}分"
        f"  同時決済{r.offset_share:6.1%}  ({r.runtime_sec:.1f}s)"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(res, out / "experiment_results.csv")
    write_html(res, spec, out / "experiment_report.html")
    print(f"出力：{out / 'experiment_results.csv'} / {out / 'experiment_report.html'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bojnet_sim", description="日銀ネット 学習用模擬システム")
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("demo", help="デモシナリオを実行")
    d.add_argument("scenarios", nargs="*")
    d.set_defaults(fn=_cmd_demo)
    for name, fn, help_ in (("simulate", _cmd_simulate, "乱数ワークロードで1日を模擬"),
                            ("experiment", _cmd_experiment, "流動性水準×方式の比較実験")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--participants", type=int, default=20)
        s.add_argument("--payments", type=int, default=1500)
        s.add_argument("--seed", type=int, default=1)
        s.add_argument("--out", default="output")
        s.set_defaults(fn=fn)
        if name == "simulate":
            s.add_argument("--theta", type=float, default=0.3, help="初期流動性（即時決済に必要な額に対する比率）")
            s.add_argument("--multilateral", choices=["scheduled", "continuous", "off"], default="scheduled")
        else:
            s.add_argument("--steps", type=int, default=7, help="θ を 0.1〜1.0 で何点とるか")
    a = ap.parse_args(argv)
    if not a.cmd:
        a = ap.parse_args(["demo", *(argv or [])])
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
