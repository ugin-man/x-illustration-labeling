# イラスト卒論：AI分類の実行基盤

20,758投稿・26,612画像参照を、独立したCodex Cloud担当が自分で予約して処理する。
GitHubは非公開。元データ・既存の人手回答は変更しない。

**現在は起動前の準備段階。AIによる本番ラベルはまだない。**
パイロット用の分類仕様と実行コードを用意した。Cloudでの画像入力・Git認証は最初の実機確認が必要。

- `data/catalog.json`: 固定入力台帳。416バッチ、通常50投稿以下。画像の全SHA-256を検査済み。
- [data-v1 Release](../../releases/tag/data-v1): 画像バッチ。担当分だけダウンロードする。
- `pipeline/worker.py`: 自主予約、入力取得、JSON雛形、検証、保存、チェックポイント、完了。
- `pipeline/git_queue.py`: バッチ別のGitブランチで原子的に予約する。担当用常設サーバーは不要。
- `pipeline/collect.py`: 検証してJSONL・投稿単位CSV・要確認一覧へ集約する。
- `docs/WORKER.md`: 担当用の短い実行手順。
- `docs/OPERATIONS.md`: 起動前・試験・障害時の手順。
- `review/classification_redesign.md`: 元アプリの24項目を見直した理由。
- `review/terra_labeling_manual_draft.md`: 判定基準。推測で不明を埋めない。

Python 3.10以降とGitのみ。APIキーによるモデル呼び出しは実装しない。
モデルの画像判断はCodex自身が行い、このCLIは入出力と整合性を担当する。

```sh
python -m unittest discover -s tests -v
python -m pipeline.worker contract
```

人手が40投稿/時なら20,758投稿で約519時間。40画像/時なら26,612画像参照で約665時間。
22,000画像を40画像/時で処理する場合は550時間。投稿と画像の単位を区別する。
Cloud並列化の実効速度・利用枠・必要日数はパイロットの実測後に判断する。
