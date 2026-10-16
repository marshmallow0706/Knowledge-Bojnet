"""システム設定（稼働時間・同時決済のスケジュール・金利・承認）。

公表情報に基づく値と、学習用に置いた「モデル値」を区別して記載する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass
class SystemConfig:
    # --- 稼働時間（公表値）-------------------------------------------------
    open_time: time = time(8, 30)            # オンライン入力開始
    month_end_open_time: time = time(7, 30)  # 月末日（年末日除く）
    cutoff_time: time = time(21, 0)          # オンライン入力締切

    # --- 同時決済口（流動性節約機能）--------------------------------------
    # 公表資料：二者間の探索は残高・待ち行列の変化の都度、多者間の探索は1日数回の定時
    # （2008年の第1期資料では1日4回、2012年の分析では1日5回と記載）。
    # 以下の時刻はモデル値であり、実際の時刻ではない。
    lsf_open_time: time = time(9, 0)
    lsf_close_time: time = time(17, 0)       # モデル値：同時決済口の受付終了
    multilateral_times: tuple[time, ...] = (
        time(9, 0), time(11, 0), time(13, 0), time(15, 0), time(16, 59),
    )
    # "scheduled"（定時のみ）/ "continuous"（イベントごと）/ "off"（多者間探索なし）
    multilateral_mode: str = "scheduled"
    bilateral_enabled: bool = True           # 二者間探索（イベント駆動）
    auto_cancel_times: tuple[time, ...] = () # 未決済指図の自動取消時刻（モデル値。既定なし）

    # --- 通常口 -----------------------------------------------------------
    # 通常口のRTGSは残高（＋日中当座貸越）不足なら拒絶する（"reject"）。
    # 学習のために待機させたい場合は "queue"。
    regular_shortage: str = "reject"

    # --- 金利（設定値：実際の基準貸付利率は日本銀行の公表値を参照）------------
    base_lending_rate: float = 0.0075        # 基準貸付利率（設定値の例）
    overdue_penalty_add: float = 0.06        # 日中当座貸越の延滞利息：基準貸付利率＋年6％（規程）

    # --- 承認（マルチ承認）---------------------------------------------------
    approval_threshold: int | None = None    # この金額以上は入力者と別の承認者が必要

    # --- 担保 -------------------------------------------------------------
    default_haircut: float = 0.02

    extra: dict = field(default_factory=dict)
