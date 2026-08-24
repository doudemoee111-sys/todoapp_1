# web/parts — ブラウザ版の部品

`python web/build.py` がここから `web/ebay.html` と `web/shopee.html` を組み立てます。
**部品を直したら必ずビルドし直してください。** 出力側を直接編集すると次のビルドで消えます。

| ファイル | 中身 |
|---|---|
| `core.js` | **計算のすべて。** 利益・送料・判定・値決め・セット販売・取り込み。DOMには触らない |
| `shell.css` | 2つのツールで共通の外枠。アクセント色だけビルド時に差し替える |
| `grid.js` | 商品一覧（仮想スクロール）。数千行でも見えている範囲しか描かない |
| `app.js` | 設定・画面切り替え・CSVの読み書き・保存 |
| `find.html/.js` | ①探す。国内APIの条件を組み立ててコマンドを出す |
| `pick.html/.js` | ②選ぶ。列の定義と一覧 |
| `list-ebay.*` / `list-shopee.*` | ③出す。ここだけ市場で中身が違う |
| `track.html/.js` | ④追う |
| `set.html` / `how-*.html` | 設定・使い方 |
| `boot-ebay.js` / `boot-shopee.js` | ツール固有の定数と起動。**スクリプトの先頭に置く**（`TOOL_ID` を他が読むため） |
| `parity.js` | `tests/test_parity.py` が node で叩く口。Python と同じ数字が出るかを見る |

`links.json` があると、ツール同士のリンクをそこに書いたURLに差し替えます（公開先が別URLになるため）。

## 直すときの順番

```bash
# 1. parts/ を編集
# 2. ビルド
python web/build.py
# 3. Python と一致しているか
python -m pytest tests/test_parity.py -q
```

計算に手を入れたときは、**必ず `tests/test_parity.py` にケースを足してください。**
画面とCLIで違う判断が出る状態は、目で見ても気づけません。
