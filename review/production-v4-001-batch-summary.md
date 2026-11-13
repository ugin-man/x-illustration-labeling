# バッチ運用への見直しと実機確認

2026-11-14 08:41 JST時点、既存Terra 10担当すべてが実行中。共有保存は **5,712 / 20,628投稿**。サブエージェントや新しい担当チャットは作成していない。

## 原因と変更

直近の停止にはCloud実行接続の `exec-server transport disconnected`、プロセスID消失、ツールの `aborted by user` 通知があった。通知の中断主体やサービス内部の発生元は未確定で、GitHub障害だったとは断定できない。

自作ツール側では、本来ローカルで済むnext/save/context summaryまで共有ロック・Git読取に依存していた。合成入力と実Gitで数えると、1投稿の通常4処理でGit通信コマンドが76回。新バッチ版では0回。共有checkpointは25回から5回に減り、10投稿または10分ごとに結果と取得履歴をまとめて送る。

現在の入口は `ops_batch.worker`、運用マニュアルは `docs/WORKER_BATCH.md`。50投稿ずつ自分で取得して繰り返す。途中の仕事は元担当に残し、期限切れだけで他担当へ渡さない。切断後はローカルのresults/draft/cache/探索ledgerと共有の受理状態を確認し、続きから復帰する。

分類schema・必須項目・探索予算・人間除外30投稿は変更していない。画像表示前の隔離監査とnextの実ファイルhash検証、実際の拒否時の暫定除外、受理済み結果の不変性を維持した。通常の本文取得失敗だけで投稿全体や担当全体を止めない。

## 確認できた結果

- 全10担当で、新しい通常投稿2件ずつ、合計20件について、許可パスのnext、実画像表示イベント、除外一致0、固定validator、共有Gitの受理結果を照合した。親は研究画像を開いていない。
- 20件の実コマンド時間はnext中央値0.278秒（0.147〜0.530秒）、save中央値0.318秒（0.199〜0.578秒）。draft作成から記入終了までは中央値61.49秒（45.70〜176.54秒）。画像の複雑さなどを揃えた速度比較ではない。
- 切替前5,641投稿の保存結果を保全確認。担当中10jobの既存272投稿blobと既存metadataは不変、他5,369投稿はjob head自体が不変。差分不一致0。
- `python -m unittest discover -s tests -v` は237件、失敗0・エラー0・スキップ1。最終的な中断回復コードについてruntime12件を再検証して成功。実Gitの10並列claim・並列batch commit・応答消失の3件も成功。
- 区分を完了して次を自動取得する動き、保留をneeds_reviewのまま残して次の通常区分へ進む動きを実機で確認した。
- 既存の毎時送信automation 10は新手順へ更新してACTIVEに戻した。送信係には監視や割当の役割を追加していない。

Cloud接続の切断そのものをこのコードで解消したとは扱わない。今回除去したのは、毎投稿の多数のGit通信に作業全体が依存する構造である。

## 再現・監査記録

- 計測: `tools/measure_batch_transport.py`、`review/production-v4-001-batch-transport-measurement.json`
- 実機照合: `tools/verify_batch_live.py`、`review/production-v4-001-batch-live-verification.json`
- 保全確認: `review/production-v4-001-batch-baseline.json`、`review/production-v4-001-batch-preservation.json`
- テスト: `review/production-v4-001-batch-tests.json`
- 起動確認・現状: `review/production-v4-001-batch-ready.json`、`review/production-v4-001-batch-status.json`

稼働revision: ops-batch-v1。manifest SHA256: `5929abc283003e7b8309917b66ca8a3bb2a77d2a01279242d15062655ce32c11`。開始commit: `32e9b214449c52063c7152fd5ef40a1446d6c4b1`。branch: `codex/production-v4-001-batch`。過去の固定revisionは履歴として保持し、通常処理には併用しない。
