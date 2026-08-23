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
| `weight_g` | ○ | 重量。送料と除外判定に使う |
| `category` | | 分類 |
| `market_price_usd` | | eBayでの想定売価。空ならAPIから取得 |
| `competitor_count` | | 現行出品数。空ならAPIから取得 |
| `has_demand_signal` | | `yes` で需要の裏付けあり |
| `demand_note` | | 裏付けの内容（落札実績など） |
| `is_restricted` | | `yes` で除外 |
| `restricted_reason` | | 除外の理由 |

**`market_price_usd` と `competitor_count` を両方埋めるとAPIを呼びません。**
API未契約の期間は、Terapeak等で手動調査した値をここに入れて運用できます。

## observations.csv の列

`sku`, `listed_on`(YYYY-MM-DD), `observed_on`(YYYY-MM-DD), `views`, `watchers`, `sold`

eBay Seller Hub のパフォーマンスレポートからエクスポートした値を想定しています。
