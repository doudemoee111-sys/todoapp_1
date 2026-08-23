# blueocean — 軸1＋軸2 統合ツール

[提案④ 補論](../../docs/business-plan/proposal-04-cross-border-export/DROPSHIP-ANALYSIS.md) で提示した
**軸1（リサーチの向きを逆にする）** と **軸2（無在庫を需要検知センサーとして使い、当たりだけ有在庫化する）**
を1本のパイプラインに統合したツールです。

---

## なぜこの2つは「組み合わせる」必要があるのか

調査の過程で、設計を決定づける制約が見つかりました。

> **eBayの Marketplace Insights API（落札実績の取得）は、主要パートナー以外に開放されていません。**

つまり個人セラーは「何がいくらで売れたか」を外部データとして買えません。
一方、**Browse API（現在出品中の検索）は公開されており、個人でも使えます。**

| 欲しいデータ | 取得手段 | 個人が使えるか |
|---|---|---|
| 競合の出品数・価格帯 | **Browse API** | **使える** |
| 落札実績（何が売れたか） | Marketplace Insights API | **使えない** |

**軸1だけでは「競合がいない」ことは分かっても「売れる」ことは分かりません。**
競合ゼロは、需要がないから誰も出していないだけかもしれない。

ここを埋めるのが軸2です。**自分の出品の反応（閲覧・ウォッチ・販売）が、
個人が手に入れられる唯一の需要データになります。**

```
軸1  Browse APIで「競合が少ない」を判定  →  だが「売れる」かは分からない
                     ↓
              少量で出品して反応を見る
                     ↓
軸2  閲覧・ウォッチ・販売から需要を確定  →  当たりだけ有在庫化
                     ↓
              その実績が次の軸1の判定材料になる（ループ）
```

**2つは別々の施策ではなく、データの欠落を互いに埋め合う1つのループです。**
だからツールとして統合する意味があります。

---

## インストール

```bash
cd tools/blueocean
pip install -r requirements.txt
```

## 使い方

### 仕入上限の逆算（まずこれを触ってください）

```bash
python -m blueocean.cli margin --price 200 --cost 12000
```

```
市場 ebay_us / セラーレベル above_standard / 売価 $200.00
目標利益率 20% を満たす仕入上限（税込）: 12,749 円
必要な「売価 ÷ 仕入」倍率: 2.35 倍

--- 内訳 ---
  売価                30000
  手数料               -5460
  関税                -3750
  送料                -3000
  梱包                 -200
  仕入               -12000
  消費税還付              1091
  利益                 6681
  利益率               22.3%
```

市場とセラーレベルを変えると、難易度が変わることが確認できます。

```bash
python -m blueocean.cli --market shopee_sea margin --price 200      # 1.41倍
python -m blueocean.cli --level below_standard margin --price 200   # 2.79倍
python -m blueocean.cli --no-tax-refund margin --price 200          # 免税事業者
```

### 軸1：出品候補を判定する

```bash
python -m blueocean.cli axis1 --candidates data/candidates.sample.csv --out plan.csv
```

```
[BLUE ]  99.9  競合   2  利益率 25.6%  Konica Hexanon AR 40mm F1.8
           - 競合 2件。値下げ圧力を受けにくい
           - 需要の裏付け：近縁モデルの落札あり
[PROBE] 113.0  競合   0  利益率 25.8%  山下達郎 FOR YOU 帯付 LP
           - 競合0件だが需要の裏付けが無い。少量で反応を試す（軸2へ）
[THIN ]   0.0  競合   3  利益率 18.8%  Pilot Custom 823 fountain pen amber
           - 採算割れ：仕入 24,000円 が上限 23,367円 を 633円 超過
[EXCL ]   0.0  競合   9  利益率  n/a  Makita cordless driver 18V with battery
           - 除外：リチウム電池内蔵で航空輸送規制
```

判定は5種類です。

| 判定 | 意味 | 次の行動 |
|---|---|---|
| `BLUE` | 競合が少なく、需要の裏付けもある | 最優先で出品 |
| `PROBE` | 競合は少ないが需要が未確認 | **少量で出して軸2で確かめる** |
| `THIN` | 採算が目標に届かない | 見送り（仕入値が下がれば再評価） |
| `RED` | 競合過多 | 見送り |
| `EXCLUDE` | 規制品・重量超過・低単価 | 対象外 |

**競合ゼロを自動的に `BLUE` にしないのが、このツールの肝です。**
「誰も出していない＝売れない」可能性を必ず残し、`PROBE` として少量検証に回します。

### 軸2：出品後の反応から次の一手を決める

```bash
python -m blueocean.cli axis2 --observations data/observations.sample.csv \
    --total-orders 120 --seller-cancellations 5
```

```
[PROMOTE] LENS-002   34日 / 閲覧 142 / ウォッチ  5 / 販売1
            1件 販売済み。需要が確定したので有在庫化し、ハンドリングを1〜2日に短縮する
[REPRICE] VINYL-001   22日 / 閲覧  98 / ウォッチ  0 / 販売0
            閲覧98件に対しウォッチ0。露出はあるので価格が原因
[RETITLE] REEL-001   53日 / 閲覧   6 / ウォッチ  0 / 販売0
            53日で閲覧6件。露出不足。海外バイヤーが実際に打つ語彙にタイトルを組み直す
[DROP   ] FIG-001  114日 / 閲覧  21 / ウォッチ  0 / 販売0
            114日間 無反応。出品を終了して枠を空ける

[警告] 在庫切れ率 4.2% が閾値 2% を超過。Below Standard に落ちると手数料が6ポイント
      上がり、必要な仕入倍率が 2.35倍→2.79倍に悪化する。出品数を減らすこと
```

判定の意味は次のとおりです。

| 判定 | シグナル | 意味 |
|---|---|---|
| `PROMOTE` | 販売あり／期間内にウォッチ3件以上 | **有在庫化する。当たり** |
| `REPRICE` | 閲覧は多いがウォッチ0 | 露出はある。価格が原因 |
| `RETITLE` | 30日で閲覧10件未満 | そもそも見られていない。検索語を直す（軸4） |
| `DROP` | 90日無反応 | 畳んで出品枠を空ける |
| `KEEP` | 上記以外 | 観察継続 |

**在庫切れ率の警告が最も重要です。** セラー都合キャンセルが積もると Below Standard に落ち、
落札手数料に6ポイント上乗せされます。利益率20%の前提そのものが崩れるため、
このツールは毎回この数字を出します。

---

## データの制約について

| データ | 取得方法 | 備考 |
|---|---|---|
| 競合出品数・価格帯 | **eBay Browse API** | 個人の開発者アカウントで利用可 |
| 落札実績 | Marketplace Insights API | **主要パートナー以外は不可** |
| 出品後の反応 | eBay Seller Hub のレポート | CSVでエクスポートして読み込む |
| 国内の仕入候補 | **手動CSV**（既定） | スクレイピングは規約違反になりうるため自動化しない |

**国内ECのスクレイピングは実装していません。** メルカリ・ヤフオクは規約で
「手元にない商品の出品」やデータの自動取得を制限しており、規約に適合しない取得手段を
既定にすべきではないと判断したためです。公式APIや正規のデータ提供が使える場合のみ、
`blueocean/sources/` にアダプタを追加してください。

**認証情報が無い場合は `MockSource` が使われます。** 決定的な擬似データを返すだけなので、
パイプラインの動作確認には使えますが、**判断には絶対に使わないでください**（実行時に警告を出します）。

### eBay Browse API を使う場合

```bash
python -m blueocean.cli axis1 \
    --candidates data/candidates.csv \
    --ebay-client-id "$EBAY_CLIENT_ID" \
    --ebay-client-secret "$EBAY_CLIENT_SECRET" \
    --out plan.csv
```

CSVに `market_price_usd` と `competitor_count` の両方を書いておけば、APIを呼びません。
API未契約の期間は、Terapeak等で手動調査した値を入れて運用できます。

---

## 設定できる前提

**関税率は流動的です。** 米国の制度はこの半年で3回変わりました（de minimis廃止 →
最高裁の違法判決 → 通商法122条 → 301条）。`blueocean/profit.py` の `DEFAULT_PROFILES`
は2026年8月時点の値なので、**運用前に必ず現在の値を確認して上書きしてください。**

```python
from blueocean.models import FeeProfile, Market
from blueocean.profit import DEFAULT_PROFILES

DEFAULT_PROFILES[Market.EBAY_US] = FeeProfile(
    market=Market.EBAY_US,
    fee_rate=0.18,        # eBay手数料の実効値
    per_order_fee_jpy=60,
    duty_rate=0.125,      # ← ここを最新の値に
    shipping_jpy=3000,
    packaging_jpy=200,
)
```

---

## テスト

```bash
python -m pytest tests -q
```

32件。利益計算は逆算と順算が一致することを含めて検証しています。

---

## 構成

```
blueocean/
├── models.py       データ構造
├── profit.py       利益計算エンジン（手数料・関税・送料・消費税還付）
├── scoring.py      軸1：ブルーオーシャン判定
├── promotion.py    軸2：有在庫化・価格見直し・撤退の判定
├── pipeline.py     軸1と軸2を繋ぐ
├── cli.py          コマンドライン
└── sources/        eBay側のデータ取得（Browse API / モック）
```

---

## このツールがやらないこと

- **出品そのもの** — SAATS Commerce等の既存ツールが担当します。本ツールは出品候補CSVを渡すところまで
- **国内ECの自動巡回** — 規約上の理由（上記）
- **落札実績の取得** — API制約（上記）。軸2が代替します

**既存の出品ツールと競合しません。** 既存ツールが持っていない「判断」の部分だけを埋めます。

---

> 本ツールの計算は2026年8月時点の調査に基づく前提値を使っています。収益を保証するものではありません。
> 関税・手数料・プラットフォーム規約は変更されます。運用前に必ず最新情報をご確認ください。
