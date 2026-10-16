"""ISO 20022 電文（簡略版）の生成・解析。

扱う電文（学習用に項目を絞った簡略版。実際の日銀ネット電文の項目・必須性・コード値とは異なる）
  pacs.009.001.08  FI Credit Transfer          金融機関間の資金振替（支払指図）
  pacs.002.001.10  Payment Status Report       状態通知（受付・待機・決済・拒絶）
  camt.050.001.05  Liquidity Credit Transfer   流動性振替（通常口 ⇄ 同時決済口）
  camt.053.001.08  Bank to Customer Statement  当座預金の取引明細（日次）
  sese.023.001.09  Securities Settlement Transaction Instruction  国債DVP指図
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from .models import Account, Category, DvpInstruction, PaymentInstruction, Status

JST = timezone(timedelta(hours=9), "JST")
NS = {
    "pacs.009": "urn:iso:std:iso:20022:tech:xsd:pacs.009.001.08",
    "pacs.002": "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.10",
    "camt.050": "urn:iso:std:iso:20022:tech:xsd:camt.050.001.05",
    "camt.053": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08",
    "sese.023": "urn:iso:std:iso:20022:tech:xsd:sese.023.001.09",
}
# 決済の種類 ⇔ 種類コード（本模擬独自の Proprietary コード）
CATEGORY_CODE = {
    Category.CALL: "CALL",
    Category.LARGE_DOMESTIC: "ZGHV",
    Category.FX_YEN: "FXYN",
    Category.INTERBANK: "INTB",
}
CODE_CATEGORY = {v: k for k, v in CATEGORY_CODE.items()}


class MessageError(ValueError):
    """電文の形式不備。"""


# ---------------------------------------------------------------- 共通
def _iso(d: datetime) -> str:
    return (d if d.tzinfo else d.replace(tzinfo=JST)).isoformat()


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrib) -> ET.Element:
    el = ET.SubElement(parent, tag, attrib)
    if text is not None:
        el.text = text
    return el


def _agent(parent: ET.Element, tag: str, member_id: str) -> None:
    fi = _sub(_sub(parent, tag), "FinInstnId")
    _sub(_sub(fi, "ClrSysMmbId"), "MmbId", member_id)


def _doc(kind: str, root_tag: str) -> tuple[ET.Element, ET.Element]:
    ET.register_namespace("", NS[kind])
    doc = ET.Element(f"{{{NS[kind]}}}Document")
    return doc, ET.SubElement(doc, root_tag)


def _dump(doc: ET.Element) -> str:
    ET.indent(doc)
    return ET.tostring(doc, encoding="unicode")


def _load(xml_text: str, kind: str) -> tuple[ET.Element, dict]:
    try:
        doc = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise MessageError(f"XML parse error: {e}") from e
    if doc.tag != f"{{{NS[kind]}}}Document":
        raise MessageError(f"名前空間が {kind} ではありません")
    return doc, {"p": NS[kind]}


def _req(doc: ET.Element, ns: dict, path: str) -> str:
    el = doc.find(path, ns)
    if el is None or el.text is None or not el.text.strip():
        raise MessageError(f"必須項目がありません: {path}")
    return el.text.strip()


def _amount(doc, ns, path) -> int:
    el = doc.find(path, ns)
    if el is None:
        raise MessageError(f"必須項目がありません: {path}")
    if el.get("Ccy") != "JPY":
        raise MessageError("通貨は JPY のみ取扱い可能です")
    try:
        v = int(el.text)
    except (TypeError, ValueError) as e:
        raise MessageError("金額は円単位の整数で指定してください") from e
    if v <= 0:
        raise MessageError("金額は正の値で指定してください")
    return v


# ---------------------------------------------------------------- pacs.009
def build_pacs009(p: PaymentInstruction, msg_id: str, created: datetime,
                  settle_date: str | None = None) -> str:
    doc, root = _doc("pacs.009", "FICdtTrf")
    hdr = _sub(root, "GrpHdr")
    _sub(hdr, "MsgId", msg_id)
    _sub(hdr, "CreDtTm", _iso(created))
    _sub(hdr, "NbOfTxs", "1")
    _sub(_sub(hdr, "SttlmInf"), "SttlmMtd", "CLRG")
    tx = _sub(root, "CdtTrfTxInf")
    pid = _sub(tx, "PmtId")
    _sub(pid, "InstrId", p.instr_id)
    _sub(pid, "EndToEndId", p.end_to_end_id or p.instr_id)
    _sub(pid, "UETR", str(uuid.uuid5(uuid.NAMESPACE_URL, msg_id + p.instr_id)))
    tp = _sub(tx, "PmtTpInf")
    _sub(tp, "ClrChanl", "RTNS" if p.account is Account.LSF else "RTGS")
    _sub(_sub(tp, "CtgyPurp"), "Prtry", CATEGORY_CODE[p.category])
    _sub(tx, "IntrBkSttlmAmt", str(p.amount), Ccy="JPY")
    _sub(tx, "IntrBkSttlmDt", settle_date or created.date().isoformat())
    _agent(tx, "InstgAgt", p.debtor)
    _agent(tx, "InstdAgt", p.creditor)
    _agent(tx, "Dbtr", p.debtor)
    _agent(tx, "Cdtr", p.creditor)
    return _dump(doc)


def parse_pacs009(xml_text: str) -> tuple[str, PaymentInstruction]:
    doc, ns = _load(xml_text, "pacs.009")
    tx = "p:FICdtTrf/p:CdtTrfTxInf"
    msg_id = _req(doc, ns, "p:FICdtTrf/p:GrpHdr/p:MsgId")
    ctg = doc.find(f"{tx}/p:PmtTpInf/p:CtgyPurp/p:Prtry", ns)
    code = ctg.text if ctg is not None else "CALL"
    if code not in CODE_CATEGORY:
        raise MessageError(f"未定義の種類コード: {code}")
    debtor = _req(doc, ns, f"{tx}/p:Dbtr/p:FinInstnId/p:ClrSysMmbId/p:MmbId")
    instg = doc.find(f"{tx}/p:InstgAgt/p:FinInstnId/p:ClrSysMmbId/p:MmbId", ns)
    if instg is not None and instg.text != debtor:
        raise MessageError("InstgAgt と Dbtr が一致しません（自行口座からの支払のみ可）")
    p = PaymentInstruction(
        instr_id=_req(doc, ns, f"{tx}/p:PmtId/p:InstrId"),
        end_to_end_id=_req(doc, ns, f"{tx}/p:PmtId/p:EndToEndId"),
        debtor=debtor,
        creditor=_req(doc, ns, f"{tx}/p:Cdtr/p:FinInstnId/p:ClrSysMmbId/p:MmbId"),
        amount=_amount(doc, ns, f"{tx}/p:IntrBkSttlmAmt"),
        category=CODE_CATEGORY[code],
    )
    return msg_id, p


# ---------------------------------------------------------------- pacs.002
def build_pacs002(orig_msg_id: str, p: PaymentInstruction | DvpInstruction, created: datetime) -> str:
    doc, root = _doc("pacs.002", "FIToFIPmtStsRpt")
    hdr = _sub(root, "GrpHdr")
    _sub(hdr, "MsgId", f"STS-{orig_msg_id}-{p.status.iso_code}")
    _sub(hdr, "CreDtTm", _iso(created))
    _sub(_sub(root, "OrgnlGrpInfAndSts"), "OrgnlMsgId", orig_msg_id)
    tx = _sub(root, "TxInfAndSts")
    _sub(tx, "OrgnlInstrId", p.instr_id)
    _sub(tx, "OrgnlEndToEndId", getattr(p, "end_to_end_id", "") or p.instr_id)
    _sub(tx, "TxSts", p.status.iso_code)
    if p.reason and p.status is not Status.SETTLED:
        _sub(_sub(_sub(tx, "StsRsnInf"), "Rsn"), "Prtry", p.reason)
    if p.settled_at:
        _sub(_sub(tx, "FctvIntrBkSttlmDt"), "DtTm", _iso(p.settled_at))
    return _dump(doc)


def parse_pacs002(xml_text: str) -> dict:
    doc, ns = _load(xml_text, "pacs.002")
    tx = "p:FIToFIPmtStsRpt/p:TxInfAndSts"
    rsn = doc.find(f"{tx}/p:StsRsnInf/p:Rsn/p:Prtry", ns)
    return {
        "orig_msg_id": _req(doc, ns, "p:FIToFIPmtStsRpt/p:OrgnlGrpInfAndSts/p:OrgnlMsgId"),
        "instr_id": _req(doc, ns, f"{tx}/p:OrgnlInstrId"),
        "status": _req(doc, ns, f"{tx}/p:TxSts"),
        "reason": rsn.text if rsn is not None else "",
    }


# ---------------------------------------------------------------- camt.050
def build_camt050(msg_id: str, code: str, amount: int, to: Account, created: datetime) -> str:
    doc, root = _doc("camt.050", "LqdtyCdtTrf")
    hdr = _sub(root, "MsgHdr")
    _sub(hdr, "MsgId", msg_id)
    _sub(hdr, "CreDtTm", _iso(created))
    tr = _sub(root, "LqdtyCdtTrf")
    frm = Account.REGULAR if to is Account.LSF else Account.LSF
    _sub(_sub(_sub(tr, "CdtrAcct"), "Id"), "Othr").append(_id(f"{code}-{_acc(to)}"))
    _sub(tr, "TrfdAmt").append(_amt(amount))
    _sub(_sub(_sub(tr, "DbtrAcct"), "Id"), "Othr").append(_id(f"{code}-{_acc(frm)}"))
    _sub(tr, "SttlmDt", created.date().isoformat())
    return _dump(doc)


def parse_camt050(xml_text: str) -> tuple[str, str, int, Account]:
    doc, ns = _load(xml_text, "camt.050")
    base = "p:LqdtyCdtTrf/p:LqdtyCdtTrf"
    cdtr = _req(doc, ns, f"{base}/p:CdtrAcct/p:Id/p:Othr/p:Id")
    code, acc = cdtr.rsplit("-", 1)
    amount = _amount(doc, ns, f"{base}/p:TrfdAmt/p:AmtWthCcy")
    to = Account.LSF if acc == "LSF" else Account.REGULAR
    return _req(doc, ns, "p:LqdtyCdtTrf/p:MsgHdr/p:MsgId"), code, amount, to


def _acc(a: Account) -> str:
    return "LSF" if a is Account.LSF else "REG"


def _id(v: str) -> ET.Element:
    el = ET.Element("Id")
    el.text = v
    return el


def _amt(v: int) -> ET.Element:
    el = ET.Element("AmtWthCcy", Ccy="JPY")
    el.text = str(v)
    return el


# ---------------------------------------------------------------- camt.053
def build_camt053(engine, code: str, account: Account = Account.REGULAR,
                  opening_balance: int | None = None) -> str:
    """当日の決済済取引から口座明細を作成する（資金決済・DVP資金）。"""
    entries = []
    for x in engine.history.values():
        if x.status is not Status.SETTLED or x.settled_at is None:
            continue
        if isinstance(x, PaymentInstruction) and x.account is account and code in (x.debtor, x.creditor):
            entries.append((x.settled_at, x.instr_id, x.amount, "DBIT" if x.debtor == code else "CRDT",
                            CATEGORY_CODE[x.category]))
        elif isinstance(x, DvpInstruction) and account is Account.REGULAR and x.cash and \
                code in (x.seller, x.buyer):
            entries.append((x.settled_at, x.instr_id, x.cash, "DBIT" if x.buyer == code else "CRDT", "DVP"))
    entries.sort()
    closing = engine.ledger.balance(code, account)
    net = sum(a if d == "CRDT" else -a for _, _, a, d, _ in entries)
    opening = closing - net if opening_balance is None else opening_balance

    doc, root = _doc("camt.053", "BkToCstmrStmt")
    hdr = _sub(root, "GrpHdr")
    _sub(hdr, "MsgId", f"STMT-{code}-{_acc(account)}-{engine.business_date:%Y%m%d}")
    _sub(hdr, "CreDtTm", _iso(engine.now))
    st = _sub(root, "Stmt")
    _sub(st, "Id", f"{code}-{engine.business_date:%Y%m%d}")
    _sub(_sub(_sub(st, "Acct"), "Id"), "Othr").append(_id(f"{code}-{_acc(account)}"))
    for tp, val in (("OPBD", opening), ("CLBD", closing)):
        b = _sub(st, "Bal")
        _sub(_sub(_sub(b, "Tp"), "CdOrPrtry"), "Cd", tp)
        _sub(b, "Amt", str(abs(val)), Ccy="JPY")
        _sub(b, "CdtDbtInd", "CRDT" if val >= 0 else "DBIT")
    for at, ref, amt, ind, kind in entries:
        n = _sub(st, "Ntry")
        _sub(n, "Amt", str(amt), Ccy="JPY")
        _sub(n, "CdtDbtInd", ind)
        _sub(n, "Sts").append(_cd("BOOK"))
        _sub(_sub(n, "BookgDt"), "DtTm", _iso(at))
        _sub(n, "AcctSvcrRef", ref)
        _sub(_sub(_sub(n, "BkTxCd"), "Prtry"), "Cd", kind)
    return _dump(doc)


def _cd(v: str) -> ET.Element:
    el = ET.Element("Cd")
    el.text = v
    return el


# ---------------------------------------------------------------- sese.023
def build_sese023(d: DvpInstruction, msg_id: str, created: datetime, side: str = "DELI") -> str:
    """国債DVP指図。side: DELI（渡し）/ RECE（受け）。"""
    doc, root = _doc("sese.023", "SctiesSttlmTxInstr")
    _sub(root, "TxId", d.instr_id)
    tp = _sub(root, "SttlmTpAndAddtlParams")
    _sub(tp, "SctiesMvmntTp", side)
    _sub(tp, "Pmt", "APMT")                       # Against Payment = DVP
    trd = _sub(root, "TradDtls")
    _sub(_sub(trd, "SttlmDt"), "Dt", created.date().isoformat())
    _sub(_sub(root, "FinInstrmId"), "ISIN", d.isin)
    q = _sub(_sub(_sub(root, "QtyAndAcctDtls"), "SttlmQty"), "Qty")
    _sub(q, "FaceAmt", str(d.face))
    parties = _sub(root, "SttlmPties")
    _sub(_sub(parties, "Dlvrg"), "Id", d.seller)
    _sub(_sub(parties, "Rcvg"), "Id", d.buyer)
    _sub(_sub(_sub(root, "SttlmAmt"), "Amt"), "Val", str(d.cash)).set("Ccy", "JPY")
    if d.use_collateral:
        _sub(root, "AddtlTxInf", "SIMULTANEOUS_COLLATERAL")
    _sub(root, "MsgId", msg_id)
    return _dump(doc)


def parse_sese023(xml_text: str) -> DvpInstruction:
    doc, ns = _load(xml_text, "sese.023")
    r = "p:SctiesSttlmTxInstr"
    if _req(doc, ns, f"{r}/p:SttlmTpAndAddtlParams/p:Pmt") != "APMT":
        raise MessageError("DVP（APMT）以外の指図は本模擬では扱いません")
    extra = doc.find(f"{r}/p:AddtlTxInf", ns)
    try:
        face = int(_req(doc, ns, f"{r}/p:QtyAndAcctDtls/p:SttlmQty/p:Qty/p:FaceAmt"))
    except ValueError as e:
        raise MessageError("額面は整数で指定してください") from e
    return DvpInstruction(
        instr_id=_req(doc, ns, f"{r}/p:TxId"),
        seller=_req(doc, ns, f"{r}/p:SttlmPties/p:Dlvrg/p:Id"),
        buyer=_req(doc, ns, f"{r}/p:SttlmPties/p:Rcvg/p:Id"),
        isin=_req(doc, ns, f"{r}/p:FinInstrmId/p:ISIN"),
        face=face,
        cash=_amount(doc, ns, f"{r}/p:SttlmAmt/p:Amt/p:Val"),
        use_collateral=extra is not None and extra.text == "SIMULTANEOUS_COLLATERAL",
    )
