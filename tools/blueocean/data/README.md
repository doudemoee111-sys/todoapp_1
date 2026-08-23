# データファイル

- `candidates.sample.csv` — 軸1の入力サンプル（国内の仕入候補）
- `observations.sample.csv` — 軸2の入力サンプル（出品後の反応）

## candidates.csv の列

| 列 | 必須 | 内容 |
|---|---|---|
| `sku` | ○ | 管理用の識別子 |
| `title_ja` | ○ | 商品名。eBay検索のクエリにも使われる |
| `source_url` | | 仕入元のURL |
| `cost_incl_tax_jpy` | ○ | 仕入価格（**税込**） |
| `weight_g` | ○ | **梱包後**の実重量。送料と除外判定に使う |
| `length_cm` | | 梱包後の縦。容積重量の計算に使う |
| `width_cm` | | 梱包後の横 |
| `height_cm` | | 梱包後の高さ |
| `category` | | 分類 |
| `market_price_usd` | | eBayでの想定売価。空ならAPIから取得 |
| `competitor_count` | | 現行出品数。空ならAPIから取得 |
| `has_demand_signal` | | `yes` で需要の裏付けあり |
| `demand_note` | | 裏付けの内容（落札実績など） |
| `is_restricted` | | `yes` で除外 |
| `restricted_reason` | | 除外の理由 |

**`market_price_usd` と `competitor_count` を両方埋めるとAPIを呼びません。**
API未契約の期間は、Terapeak等で手動調査した値をここに入れて運用できます。

**寸法（`length_cm` / `width_cm` / `height_cm`）は任意ですが、入れてください。**
未入力でも動きますが、その場合は実重量だけで送料を出すため、
軽くて嵩張る商品（衣類・外箱付きフィギュア・レコード）で送料が下振れします。
容積重量で課金される商品は、寸法を入れて初めて正しく弾けます。

## rates.csv（任意）

公式料金表で既定の推定値を差し替えるためのファイルです。

```csv
zone,max_weight_g,jpy
zone3,1000,4650
zone3,2000,5900
```

`zone` は `zone1`〜`zone5`。地帯区分は
第1＝中国・韓国・台湾／第2＝アジア（第1地帯を除く）／第3＝オセアニア・北米（米国を除く）・
中近東・ヨーロッパ／第4＝**米国**／第5＝中南米・アフリカ。

`--rates data/rates.csv` で読み込みます。ここで入れた値は「推定値」の警告が付きません。

## observations.csv の列

`sku`, `listed_on`(YYYY-MM-DD), `observed_on`(YYYY-MM-DD), `views`, `watchers`, `sold`

eBay Seller Hub のパフォーマンスレポートからエクスポートした値を想定しています。
