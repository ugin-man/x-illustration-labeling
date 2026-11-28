# イラスト卒論の分類データ

**既存の卒論分析を再現する場合は、固定版 `fixed-11543` を使ってください。**

| 版 | 含まれる記録 |
| --- | --- |
| [固定版](fixed-11543/manifest.json) | 11,543処理記録（分類ラベル11,512件、ポリシー暫定除外31件） |
| [11月28日の追加版](additions-20261128/manifest.json) | 分類ラベル2,333件。前回2,048件に、Terraの共有済み209件とHydrogenの保存済み76件を追加。固定版との投稿ID重複は0件。 |

追加版は累計です。以前の分析を再現する場合は、当時の[11月26日版](https://github.com/ugin-man/x-illustration-labeling/tree/f8ba35b2534734988dc40a2a85ca08f08db5fa84/additions-20261126)または[11月24日版](https://github.com/ugin-man/x-illustration-labeling/tree/28af267de6609abf09ebaf7f64add48e2dede233/additions-20261124)のいずれかを使えます。

Terraは17:27時点のGitHub受理済み、Hydrogenは17:30時点の検証済みローカル保存を収録しています。時刻は日本時間です。[Terraの区分一覧](terra-queue-summary.json)には、その時点の共有済み件数と区分の状態を記録しています。

このコミットをチェックアウトしたディレクトリで、Python 3.10以上を使って必要な版を出力できます。

```sh
python read_dataset.py --dataset fixed-11543 --output ./fixed-export
python read_dataset.py --dataset additions-20261128 --output ./additions-export
python read_dataset.py --dataset combined --output ./combined-export
```

`combined` は固定版と、このコミットの最新追加版を結合します。分類ラベルとポリシー暫定除外は別ファイルに出力されます。
