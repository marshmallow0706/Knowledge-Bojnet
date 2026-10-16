"""電文ゲートウェイ：ISO 20022 電文を受け付けてエンジンに渡し、応答電文を返す。

参加者の「コンピュータ接続（CPU接続）」を模したもの。電文IDの重複受信は再処理せず、
前回と同じ応答を返す（冪等性）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import BojNetEngine
from .iso20022 import (MessageError, build_pacs002, parse_camt050, parse_pacs009,
                       parse_sese023)
from .models import PaymentInstruction, Status


@dataclass
class Gateway:
    engine: BojNetEngine
    seen: dict[str, str] = field(default_factory=dict)       # MsgId -> 応答
    inbox_log: list[tuple[str, str]] = field(default_factory=list)

    def receive(self, xml_text: str) -> str:
        """電文を受信して応答（pacs.002 または簡易ACK/NAK）を返す。"""
        kind = _detect(xml_text)
        try:
            if kind == "pacs.009":
                msg_id, p = parse_pacs009(xml_text)
                if msg_id in self.seen:
                    return self.seen[msg_id]
                self.engine.submit_payment(p)
                resp = build_pacs002(msg_id, p, self.engine.now)
            elif kind == "sese.023":
                d = parse_sese023(xml_text)
                msg_id = d.instr_id
                if msg_id in self.seen:
                    return self.seen[msg_id]
                self.engine.submit_dvp(d)
                resp = build_pacs002(msg_id, d, self.engine.now)
            elif kind == "camt.050":
                msg_id, code, amount, to = parse_camt050(xml_text)
                if msg_id in self.seen:
                    return self.seen[msg_id]
                ok = self.engine.transfer_liquidity(code, amount, to)
                resp = f"ACK {msg_id}" if ok else f"NAK {msg_id} LIQUIDITY_TRANSFER_REJECTED"
            else:
                return f"NAK UNSUPPORTED_MESSAGE {kind}"
        except MessageError as e:
            self.engine._log("REJECT", f"電文エラー {kind}: {e}")
            return f"NAK FORMAT_ERROR {e}"
        self.seen[msg_id] = resp
        self.inbox_log.append((kind, msg_id))
        return resp

    def status_report(self, msg_id: str, instr_id: str) -> str:
        """待機中だった指図のその後の状態を pacs.002 で再通知する。"""
        x = self.engine.history[instr_id]
        return build_pacs002(msg_id, x, self.engine.now)


def _detect(xml_text: str) -> str:
    head = xml_text[:400]
    for k in ("pacs.009", "pacs.002", "camt.050", "camt.053", "sese.023"):
        if k in head:
            return k
    return "unknown"


__all__ = ["Gateway", "PaymentInstruction", "Status"]
