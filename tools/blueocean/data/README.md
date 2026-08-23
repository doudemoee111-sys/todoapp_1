# データファイル

- `jobs.sample.json` — `job`（抽出条件の保存と再実行）の設定サンプル
- `keywords.sample.txt` — `scan`（キーワード走査）の入力サンプル
- `bundle.sample.csv` — `bundle`（セット販売の採算）の入力サンプル
- `candidates.sample.csv` — 軸1の入力サンプル（国内の仕入候補）
- `observations.sample.csv` — 軸2の入力サンプル（出品後の反応）

流れは `keywords.txt` → `scan` → `candidates.csv`（雛形）→ 国内で現物を探して仕入値を書き足す
→ `axis1` → 出品 → `observations.csv` → `axis2` です。

## jobs.json

抽出条件をここに固定すると、`job --name <ジョブ名>` で毎回同じ条件で回せます。
**同じ条件で回すからこそ、前回との差分が意味を持ちます。**
知らない項目を書くとエラーになります（綴り違いを黙って既定値にすると、
意図と違う条件で抽出し続けることになるため）。詳細は
[ツールのREADME](../README.md#抽出条件を保存してを毎回同じ条件で回す) を見てください。

## keywords.txt

1行1件。`#` 以降と空行は無視します。得意ジャンルの型番表を置いてください。
**粒度は型番まで**が基本です（ブランド単位だと競合数が意味を持たなくなります）。

```
# --- オールドレンズ（国産マニュアルフォーカス） ---
Konica Hexanon AR 40mm F1.8
Nikon Ai-s 50mm F1.2
```

一度作れば資産として残ります。100〜500行あれば毎週の走査に足ります。

## bundle.csv の列

| 列 | 必須 | 内容 |
|---|---|---|
| `name` | ○ | 構成品の名前 |
| `cost_incl_tax_jpy` | ○ | 仕入価格（税込） |
| `weight_g` | ○ | 実重量 |
| `length_cm` / `width_cm` / `height_cm` | | 寸法 |
| `solo_price_usd` | | 単品で出したときの想定売価。**空にすると「単品では売れない見込み」** |

`solo_price_usd` を空にした品は、売上が立たず原価だけが残る計算になります。
死に筋を売れ筋に混ぜる効果を測るための区別です。

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

`sku`, `title`(任意), `listed_on`(YYYY-MM-DD), `observed_on`(YYYY-MM-DD), `views`, `watchers`, `sold`

eBay Seller Hub のパフォーマンスレポートからエクスポートした値を想定しています。

**`title` を入れてください。** SKUだけを並べても「どの商品か分からない」ので、
判定を読んでも動けません。列が無い場合は `axis2 --candidates data/candidates.csv` で
候補CSVから商品名を結合できます。

**このファイルは追記して育てます。** 毎週の行を足していけば、同じSKUの行が何本も並びます。
ツールはSKUごとに最新の1行だけを判定対象にし、1つ前の行を前回比の計算に使います。
古い行を消す必要はありません（消すと前回比が出なくなります）。

```csv
sku,listed_on,observed_on,views,watchers,sold
LENS-002,2026-07-20,2026-08-16,118,3,0
LENS-002,2026-07-20,2026-08-23,142,5,1
```

## history.jsonl（ツールが書きます）

`axis1 --history data/history.jsonl` を付けると、その回の判定結果が1行1件で追記されます。
**追記のみで、既存の行は書き換えません。** 次回の実行で「前回からの変化」を出す材料になります。

```jsonl
{"taken_on": "2026-08-23", "sku": "LENS-002", "verdict": "red", "competitor_count": 34, ...}
```

手で編集する必要はありません。壊れた行があっても、その行だけ落として続行します。
`history --sku LENS-002` でそのSKUの推移を表示できます。
