# 用語集

[← トップへ戻る](./README.md)

本書で使う主な用語を五十音・アルファベット順にまとめました。右端は主に解説している章です。

## 日本語

| 用語 | 意味 | 解説 |
|---|---|---|
| アンワインド | 時点ネット決済で不履行が起きたとき、関係する取引を除いて差額を計算し直すこと | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| 延滞利息（日中当座貸越） | 終業時に日中当座貸越が残った場合にかかる利息。基準貸付利率＋年6％ | [仕様5](./01_spec/05_current_account_system.md) |
| 外国為替円決済制度 | 海外からの円送金や外為取引の円資金を集中的に決済する制度。2008年から完全RTGS | [仕組み5](./02_mechanism/05_private_system_links.md) |
| 間接参加者 | 参加者（口座管理機関）を通じて国債振替決済制度に参加する者 | [仕様6](./01_spec/06_jgb_system.md) |
| 基準貸付利率 | 補完貸付に原則適用される金利 | [仕様8](./01_spec/08_monetary_operations.md) |
| 共通担保 | 日本銀行の与信（日中当座貸越・オペ・補完貸付）を一括して保全する担保の仕組み | [仕組み4](./02_mechanism/04_intraday_liquidity.md) |
| グリッドロック | 各行が受取を待ち合い、資金があっても決済が進まない状態 | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| 国債系 | 日銀ネットのうち、国債の振替・発行・元利払いを処理する系 | [仕様6](./01_spec/06_jgb_system.md) |
| 国債振替決済制度 | 社株法に基づき、日本銀行が振替機関として運営する振替国債の決済制度 | [仕様6](./01_spec/06_jgb_system.md) |
| コンピュータ接続（CPU接続） | 参加者のホストコンピュータと日銀ネットを直接つなぎ、電文を自動でやり取りする接続形態 | [仕様3](./01_spec/03_connectivity.md) |
| 時点ネット決済（DNS） | 受払差額を決められた時点にまとめて決済する方式 | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| システミック・リスク | 1参加者の不履行が他の参加者の不履行を連鎖的に招くリスク | [仕組み6](./02_mechanism/06_risk_and_bcp.md) |
| 次世代RTGS | 2008年（第1期）・2011年（第2期）の日銀ネット改善。同時決済口、外為円・大口内為のRTGS化 | [仕様9](./01_spec/09_statistics.md) |
| 社株法 | 社債、株式等の振替に関する法律。国債振替決済制度の法的基盤 | [仕様7](./01_spec/07_participation_and_governance.md) |
| 新日銀ネット | 2014年（第1段階）・2015年10月（全面）に稼働した現行の日銀ネット | [仕様1](./01_spec/01_overview.md) |
| 振替国債 | 券面がなく、振替口座簿の記録で権利が移る国債 | [仕様6](./01_spec/06_jgb_system.md) |
| 政府預金 | 日本銀行にある政府の預金。国庫金の受払に使われる | [仕様8](./01_spec/08_monetary_operations.md) |
| 全銀システム | 全国銀行データ通信システム。内国為替（振込等）を処理し、全銀ネットが運営 | [仕組み5](./02_mechanism/05_private_system_links.md) |
| 大口内為 | 1件1億円以上の内国為替取引。2011年から日銀ネットでRTGS | [仕組み5](./02_mechanism/05_private_system_links.md) |
| 待ち行列 | 残高不足の支払指図を拒絶せずに置いておく列。各行の先頭から順に処理 | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| 担保価額 | 担保の時価に掛目を掛けた評価額 | [仕組み4](./02_mechanism/04_intraday_liquidity.md) |
| 端末接続 | 日銀ネット端末から画面操作で入力・照会する接続形態 | [仕様3](./01_spec/03_connectivity.md) |
| 通常口 | 当座勘定のうち、日本銀行との取引・時点ネット尻・DVP資金を扱い、日中当座貸越が使える勘定 | [仕様5](./01_spec/05_current_account_system.md) |
| 電子交換所 | 手形・小切手を電子的に交換する仕組み。交換尻は当日15時に日銀当預で決済 | [仕組み5](./02_mechanism/05_private_system_links.md) |
| 当預系 | 日銀ネットのうち、日本銀行当座預金の振替で資金を決済する系 | [仕様5](./01_spec/05_current_account_system.md) |
| 同時決済口 | 当座勘定のうち、流動性節約機能付きRTGSで市場取引・外為円・大口内為を扱う勘定 | [仕様5](./01_spec/05_current_account_system.md) |
| 同時担保受払 | DVPで受け取る国債をそのまま担保に差し入れ、日中当座貸越で代金を払う機能 | [仕組み4](./02_mechanism/04_intraday_liquidity.md) |
| 二者間探索 | 2行間で互いに向き合う指図の組を同時決済できるか調べる処理。変化のたびに実行 | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| 多者間探索 | 3行以上の指図の組合せを同時決済できるか調べる処理。定時に実行 | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| 日中当座貸越 | 担保の範囲で日中に限り当座預金残高を超えて支払える与信。無利息、終業時までに返済 | [仕組み4](./02_mechanism/04_intraday_liquidity.md) |
| ファイナリティ | 決済が無条件かつ取消不能となり、最終的に完了した状態 | [仕組み1](./02_mechanism/01_payment_landscape.md) |
| フリー振替 | 資金決済を伴わない国債の振替 | [仕様6](./01_spec/06_jgb_system.md) |
| プレファンドRTGS方式 | 参加行が事前に中銀マネーを民間システムに拠出し、その帳簿上で即時決済する方式 | [仕組み8](./02_mechanism/08_future_outlook.md) |
| 補完貸付 | 担保の範囲で、基準貸付利率・翌営業日返済で受動的に実行される日本銀行の貸付 | [仕様8](./01_spec/08_monetary_operations.md) |
| 流動性振替 | 通常口と同時決済口の間の資金移動 | [仕様5](./01_spec/05_current_account_system.md) |
| 流動性節約機能 | 待ち行列と同時決済により、少ない流動性で多くの指図を決済する仕組み | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| レポ取引 | 債券を担保に資金を貸借する取引。スタートとエンドの2回のDVPで決済 | [模擬](./03_simulator/README.md) |

## アルファベット

| 用語 | 意味 | 解説 |
|---|---|---|
| BOJ-NET | 日銀ネット（Bank of Japan Financial Network System）の英語名 | [仕様1](./01_spec/01_overview.md) |
| camt.050 / camt.053 | ISO 20022 の流動性振替／口座明細の電文 | [仕様4](./01_spec/04_message_format.md) |
| CBDC | 中央銀行デジタル通貨 | [仕組み8](./02_mechanism/08_future_outlook.md) |
| CLS | 外為取引の通貨を同時に受け渡す（PvP）国際的な決済機関 | [仕組み5](./02_mechanism/05_private_system_links.md) |
| DVP | Delivery versus Payment：証券と資金の同時受渡 | [仕組み3](./02_mechanism/03_jgb_dvp.md) |
| FMI | Financial Market Infrastructure：金融市場インフラ | [仕様7](./01_spec/07_participation_and_governance.md) |
| FIFO | First In, First Out：先に入った指図から処理する順序 | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| ISO 20022 | 金融通信メッセージの国際標準（XML） | [仕様4](./01_spec/04_message_format.md) |
| JSCC | 日本証券クリアリング機構。国債店頭取引などの清算機関 | [仕組み3](./02_mechanism/03_jgb_dvp.md) |
| pacs.002 / pacs.009 | ISO 20022 の状態通知／金融機関間の資金振替の電文 | [仕様4](./01_spec/04_message_format.md) |
| PFMI | CPMI-IOSCO の「金融市場インフラのための原則」 | [仕様7](./01_spec/07_participation_and_governance.md) |
| PvP | Payment versus Payment：異なる通貨の同時受渡 | [仕組み5](./02_mechanism/05_private_system_links.md) |
| RTGS | Real-Time Gross Settlement：即時グロス決済 | [仕組み2](./02_mechanism/02_rtgs_and_lsf.md) |
| sese.023 | ISO 20022 の証券決済指図の電文 | [仕様4](./01_spec/04_message_format.md) |
| STP | Straight Through Processing：約定から決済まで人手を介さず自動処理すること | [仕様3](./01_spec/03_connectivity.md) |
| UETR | Unique End-to-end Transaction Reference：送金を一意に追跡する参照番号 | [仕様4](./01_spec/04_message_format.md) |
