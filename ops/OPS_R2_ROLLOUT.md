# ops-r2 の切替記録

2026-11-13。ユーザーは停止要因を直し、全10担当と毎時送信係へ変更理由・変更箇所・再読するマニュアルを通知するよう明示した。

分類の固定runは `production-v4-001`、元commitは `4d2c98374a1364faf1e2b546a4c460e80e9b2903`。元ファイルのhashを維持し、`ops_runtime/`、`docs/WORKER_OPERATIONS_R2.md`、運用manifest/controlだけを追加する。変更を元の凍結マニュアルへ紛れ込ませない。

## 適用順序

1. 新コード、マニュアル、合成テストを完成。`python -m unittest discover -s tests -v` を実行し、失敗を解消する。
2. `private/build_ops_revision.py` で新コード・新マニュアルを固定し、controlはblockedで生成する。GitHubの専用branchに元commitを親として追加ファイルだけ公開する。
3. 既存automation ID `10` を正式なautomation操作で一時PAUSEDへ。設定・対象・間隔は維持する。
4. 全10担当へ現在の保存可能な結果をcheckpointして停止するよう伝える。誤記を含む未受理回答は保全し、無理にcheckpointしない。停止と現在rootを確認する。
5. 現在のrootへ公開commitの追加ファイルだけ導入する。runtime、受理済み、固定分類ファイルは維持する。各担当が新マニュアルを読み、変更理由・変更点・hash・blocked状態の確認をこのチャットの応答で報告する。別チャットへの返信ツールは要求しない。
6. 全10の確認後、manifest hashを束縛したenabled controlを親が公開。各担当が新controlを照合する。担当が自分でenabledへ書き換えてはならない。
7. まず1担当で改訂CLIのclaim/next/save/checkpointと実画像パス・所要時間を確認。他担当は開始連絡まで待機。その後残りを再開する。
8. 毎時送信係へ変更を知らせ、定型文を新運用参照へ更新する。送信係の役割は送信だけのまま。automation ID `10` をACTIVEへ戻し、設定を確認する。
9. 新しい全10担当の進行を確認。既存needs_reviewの再開は、拒否入力をdeferへ保存して再表示を阻止したうえで、coordinator CLIの明示操作に限る。除外審査の拒否を迂回して除外・完了にしない。

## 記録するもの

- 公開commit、manifest/controlのhash、テスト結果。
- workerごとの停止・現在root・新マニュアル読了・インストールhash・開始後の保存head。
- 毎時送信係への通知とautomation更新。
- 保留された投稿は未完了として別記録。受理済みの意味内容の精度を、この運用試験の成功で保証しない。

現時点は実装・試験中。新運用はまだ有効化していない。
