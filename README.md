# イラスト卒論の分類データ

既存の卒論分析を再現するときは、**固定版 `fixed-11543`** を使う。追加版は版名を指定して使う。

| 版 | 内容 |
| --- | --- |
| [固定版 `fixed-11543`](fixed-11543/manifest.json) | 2026年11月14日の停止時点の11,543処理記録。分類ラベル11,512件、ポリシー暫定除外31件。240本の作業ブランチを照合し、記録が入っていた238区分の内容を元のGitオブジェクトから固定した。 |
| [追加版 `additions-20261124`](additions-20261124/manifest.json) | 分類ラベル842件。別経路のKoyo回収117件、Hydrogen試行50件、Hydrogen継続作業675件。Hydrogen継続分の締切は2026年11月24日23:11 JST。固定版との投稿ID重複は0件。 |
| [回収時の確認記録](recovery-review.json) | 下書き・未確定・暫定除外の18投稿に関する出典と理由。分類ラベルの件数には含めない。 |

## 読み出し

各版の `manifest.json` に対象ファイル、投稿件数、SHA-256 がある。作業ブランチを集め直す場合にも、分析に使用する版のマニフェストを基準にする。

```sh
# 既存の卒論分析
python read_dataset.py --dataset fixed-11543 --output ./fixed-export

# 追加分の確認
python read_dataset.py --dataset additions-20261124 --output ./additions-export

# 明示的に両方を使う追加分析
python read_dataset.py --dataset combined --output ./combined-export
```

`records.jsonl` は全処理記録、`labels.jsonl` は分類ラベル、`exclusions.jsonl` はポリシー暫定除外の記録。いずれも投稿IDで照合できる。既存の分析と同じ抽出条件・人気指標データを使用する。追加版にも同じv4-1の分類基準を適用し、モデル・実行経路は行の `provenance` と追加版の出典表で確認できる。Koyo経路のモデル名は実行ログに記録されていない。

この配布版はコミット単位で固定する。後日回収したデータは新しい版として扱う。ここに置くのは分類結果と回収メタデータで、画像入力の取得は不要。
