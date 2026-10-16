# 第4章 電文仕様（ISO 20022）

[← 前章：接続方式](./03_connectivity.md) ｜ [目次](./README.md) ｜ [次章：当預系の業務仕様 →](./05_current_account_system.md)

---

## 4.1 ISO 20022 の採用

ISO 20022 は、ISO 金融サービス専門委員会（TC68）が開発した **金融通信メッセージの国際標準** です。XML による構造化データ、業務モデルに基づくメッセージ定義（リポジトリ）を特徴とします。

日本銀行は、**欧米に先駆けて日銀ネットで ISO 20022 を採用** しました（2015年の新日銀ネット全面稼働時）。

## 4.2 バージョン改訂（Version 3 → Version 8）

| 時期 | 内容 |
|---|---|
| 2015年〜 | 日銀ネットの電文（外為円決済制度で用いる電文等）は ISO 20022 **Version 3** に準拠 |
| 2023年3月〜 | SWIFT が ISO 20022（Version 8）電文の利用を開始。外為円決済制度では Version 8 の SWIFT 電文を Version 3 の日銀ネット電文に転記して対応 |
| 2025年11月22日 | SWIFT が MT 電文（クロスボーダー決済）の利用を終了 |
| **2025年11月25日** | 日銀ネットで利用する ISO 20022 電文を **Version 8 に改訂** |

バージョンを揃えることで、海外から国内受取人までの送金で **情報の欠落（トランケーション）を防ぎ**、マネー・ローンダリング対策上も重要な送金人・受取人情報をエンドツーエンドで連携できるようになります。

## 4.3 主なメッセージ類型（ISO 20022 の一般分類）

ISO 20022 のメッセージ識別子は `業務領域.メッセージ番号.バリアント.バージョン`（例：`pacs.009.001.08`）の形式です。日銀ネットで実際に用いる電文の一覧・項目定義は利用先向け仕様書で規定されます。以下は中銀RTGSで一般的に使われる類型です。

| 業務領域 | 代表メッセージ | 用途 |
|---|---|---|
| pacs（Payments Clearing and Settlement） | **pacs.009** FI Credit Transfer | 金融機関間の資金振替（銀行間送金・コール資金等） |
| | **pacs.008** FI to FI Customer Credit Transfer | 顧客送金（外為円決済の顧客送金等） |
| | **pacs.002** Payment Status Report | 受付・決済・拒絶等の状態通知 |
| | pacs.004 Payment Return | 返金 |
| camt（Cash Management） | camt.053 / camt.052 | 口座明細・残高通知 |
| | camt.054 | 入出金通知 |
| | camt.050 | 流動性振替（本書の模擬では通常口 ⇄ 同時決済口） |
| | camt.056 | 取消要求 |
| sese / semt（Securities） | sese.023 / sese.025 | 証券決済指図／決済確認 |
| | semt.017 | 証券残高明細 |

## 4.4 pacs.009 の構造（簡略例）

以下は **学習用に簡略化** した例です（本書の[模擬システム](../03_simulator/README.md)は pacs.009／pacs.002／camt.050／camt.053／sese.023 の簡略版を生成・解析します）。実際の日銀ネット電文の項目・必須性・コード値とは異なります。

```xml
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.009.001.08">
  <FICdtTrf>
    <GrpHdr>
      <MsgId>BANKA-20261016-000123</MsgId>
      <CreDtTm>2026-10-16T09:15:00+09:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <SttlmInf><SttlmMtd>CLRG</SttlmMtd></SttlmInf>
    </GrpHdr>
    <CdtTrfTxInf>
      <PmtId>
        <InstrId>INSTR-0001</InstrId>
        <EndToEndId>CALL-20261016-77</EndToEndId>
        <UETR>8a562c67-ca16-48ba-b074-65581be6f001</UETR>
      </PmtId>
      <IntrBkSttlmAmt Ccy="JPY">5000000000</IntrBkSttlmAmt>
      <IntrBkSttlmDt>2026-10-16</IntrBkSttlmDt>
      <InstgAgt><FinInstnId><ClrSysMmbId><MmbId>0001</MmbId></ClrSysMmbId></FinInstnId></InstgAgt>
      <InstdAgt><FinInstnId><ClrSysMmbId><MmbId>0005</MmbId></ClrSysMmbId></FinInstnId></InstdAgt>
      <Dbtr><FinInstnId><ClrSysMmbId><MmbId>0001</MmbId></ClrSysMmbId></FinInstnId></Dbtr>
      <Cdtr><FinInstnId><ClrSysMmbId><MmbId>0005</MmbId></ClrSysMmbId></FinInstnId></Cdtr>
    </CdtTrfTxInf>
  </FICdtTrf>
</Document>
```

### 主要項目の意味

| 項目 | 意味 |
|---|---|
| `GrpHdr/MsgId` | 送信者が付与する電文ID（重複検知に利用） |
| `PmtId/EndToEndId` | 取引の端から端までの参照番号 |
| `PmtId/UETR` | 一意の取引参照（UUID）。追跡（トラッキング）に利用 |
| `IntrBkSttlmAmt` | 銀行間決済金額（円は小数なし） |
| `IntrBkSttlmDt` | 決済日 |
| `Dbtr` / `Cdtr` | 支払側・受取側の金融機関（日銀ネットでは当座預金取引先） |

## 4.5 電文処理の基本ルール（一般原則）

1. **スキーマ検証**：XMLスキーマ（XSD）適合性を検証し、不適合は拒絶（pacs.002 で理由コード付き通知）。
2. **重複排除**：同一 MsgId / 指図IDの再送は二重決済しない。
3. **状態遷移**：受付 → 待機（待ち行列）→ 決済済 ／ 取消 ／ 拒絶。
4. **時刻管理**：決済日・締切時刻を超えた指図は拒絶または翌営業日扱い（制度による）。
5. **文字コード**：XML は UTF-8。全角文字を使える項目・使えない項目は仕様書で規定。

## 参考資料

- 日本銀行 金融研究所「金融サービスを巡る国際標準化の動向 －ISO 20022の利用拡大とFinTech関連の取組み－」（2017年） https://www.boj.or.jp/research/wps_rev/rev_2017/rev17j12.htm
- 日本銀行「日銀ネットの有効活用に向けた協議会」（ISO 20022 電文バージョン改訂の公表一覧） https://www.boj.or.jp/paym/bojnet/net_forum/index.htm
- 全国銀行協会「外国為替円決済制度における ISO20022 電文バージョン改訂について」（2025年） https://www.zenginkyo.or.jp/news/2025/n101401/
- 全国銀行協会「外国為替円決済制度におけるSWIFT電文のISO20022移行に係る対応について」（2022年12月） https://www.zenginkyo.or.jp/news/2022/n122901/
- ISO 20022 公式サイト https://www.iso20022.org/
