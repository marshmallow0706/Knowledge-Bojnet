"""監査ログ：ハッシュ連鎖による改ざん検知付きイベントログ。

各イベントは直前のイベントのハッシュを含めてSHA-256を計算する。途中の1件でも書き換えると
以降のハッシュが一致しなくなるため、verify() で検知できる。
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Event:
    no: int
    at: str
    kind: str
    detail: str
    prev_hash: str
    hash: str = ""

    def compute(self) -> str:
        body = f"{self.no}|{self.at}|{self.kind}|{self.detail}|{self.prev_hash}"
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class AuditLog:
    GENESIS = "0" * 64

    def __init__(self) -> None:
        self.events: list[Event] = []

    def append(self, at: datetime, kind: str, detail: str) -> Event:
        prev = self.events[-1].hash if self.events else self.GENESIS
        ev = Event(len(self.events) + 1, at.isoformat(timespec="seconds"), kind, detail, prev)
        ev.hash = ev.compute()
        self.events.append(ev)
        return ev

    def verify(self) -> int | None:
        """問題なければ None、改ざんを検知したらそのイベント番号を返す。"""
        prev = self.GENESIS
        for ev in self.events:
            if ev.prev_hash != prev or ev.compute() != ev.hash:
                return ev.no
            prev = ev.hash
        return None

    def of_kind(self, *kinds: str) -> list[Event]:
        return [e for e in self.events if e.kind in kinds]

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps([asdict(e) for e in self.events],
                                         ensure_ascii=False, indent=1), encoding="utf-8")

    def to_csv(self, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["no", "at", "kind", "detail", "prev_hash", "hash"])
            for e in self.events:
                w.writerow([e.no, e.at, e.kind, e.detail, e.prev_hash, e.hash])
