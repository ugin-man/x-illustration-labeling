# イラスト卒論の分類データ

**既存の卒論分析を再現する場合は、固定版 `fixed-11543` を使ってください。**

| 版 | 含まれる記録 |
| --- | --- |
| [固定版](fixed-11543/manifest.json) | 11,543処理記録（分類ラベル11,512件、ポリシー暫定除外31件） |
| [最新追加版](additions-20261126/manifest.json) | 追加ラベル2,048件（前回842件、今回のHydrogen分1,206件）。2026年11月26日13:22 JST締め。固定版との投稿IDの重複は0件。 |

[11月24日の追加版](https://github.com/ugin-man/x-illustration-labeling/tree/28af267de6609abf09ebaf7f64add48e2dede233/additions-20261124)の842件は最新追加版に含まれます。追加ラベルを使う場合は、対象とする追加版を一つ選んでください。

このコミットをチェックアウトしたディレクトリで、Python 3.10以上を使って必要なデータを書き出せます。

```sh
python read_dataset.py --dataset fixed-11543 --output ./fixed-export
python read_dataset.py --dataset additions-20261126 --output ./additions-export
python read_dataset.py --dataset combined --output ./combined-export
```

`combined` は固定版とこのコミットの最新追加版を結合します。分類ラベルとポリシー暫定除外は別のJSONLファイルに出力されます。[回収時の確認記録](recovery-review.json)は11月24日版のものです。
