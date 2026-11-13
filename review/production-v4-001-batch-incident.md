# 2026-11-14 バッチ運用の根本見直し

## 確認した事実

08:04前後のアプリ記録では04/09/10が停止し、他7担当はactiveだった。複数担当で22:52〜22:55 UTC頃にcommandExecutionのexitCode=-1があるが、同項目には失敗本文が保存されていない。各既存担当に原応答とローカル状態を確認した。

- 01/05: `write_stdin failed: Unknown process id ...`。実行プロセスIDが追跡できなくなった。
- 02/08: `exec-server transport disconnected`。02は08:11 JST、同じ環境で通常の読み取りに復帰した。08も同環境で再試行後に進んでいた。
- 04/06/07/09/10: ツール原応答に `aborted by user after ...`。ただし、誰のどの操作で中断されたかを、この文言だけでは確定できない。ユーザーの意図的中断だったとも、GitHubの障害だったとも断定しない。
- 06/07は同様の中断後に保存状態を確認して継続していた。06は前の50投稿を終え、次のprod-0268を取得していた。

今回はGitのHTTPエラーを示す新しい証拠はない。Gitのretry回数だけを増やしてもexec-server切断・中断通知は直らない。Cloudサービス内部の中断元は、取得できたツール履歴では特定できていない。

## 自作コードにあった構造上の問題

r5のworker.runはnext/save/context summaryを含むほぼ全コマンドで、新規の一時bare Git repo、共有claim gateの取得/解放、所有権・job metadataの再取得を行う。本文fetchと検索予約はさらに複数回のsidecar commitとglobal index更新を伴う。

`tools/measure_batch_transport.py` により、本物のローカルbare Gitと合成入力でGitのnetwork command（ls-remote/fetch/push）を数えた。研究画像や外部サービスは使っていない。これはHTTPパケット数やCloudでの所要時間の測定ではない。

| 処理 | r5 | 新バッチ処理 |
|---|---:|---:|
| next | 14 | 0 |
| 本文fetchに伴うGit | 34 | 0 |
| context summary | 16 | 0 |
| save | 12 | 0 |
| 共有checkpoint | 25 | 5 |

通常1投稿の前4処理だけで76回あった。本文の外部テキスト取得そのものは別で、必要な投稿に従来どおり行う。新処理は10投稿または10分ごとに結果と取得履歴をまとめて共有する。

## 変更した境界

- ops_batch.workerだけを通常入口にする。固定分類コード・schema・manual・人間除外30投稿は変更しない。
- next/context予約/summary/save/defer/exclude/inspectはローカルの原子的journalで進む。saveも従来の固定validatorを使う。
- claimとcheckpoint/finishだけが共有Gitを変更する。jobとindexのCAS、受理済み結果の不変性、同一commit受理確認を維持する。
- 期限が切れただけの仕事を別担当へ自動移管しない。元担当の未共有results、draft、cache、探索ledgerを回収して再開する。
- 各checkpointで補助報告branchを必須pushしない。共有結果と実ツール履歴を検証の正本とする。
- exec transport切断、行方不明のプロセス、Git失敗、人間/審査の停止通知を区別する。サービス側の切断をこの実装で完全になくせるとは扱わない。

移行前の受理済みは5,641投稿。全413jobのheadと、担当中10jobの結果・metadata blobをbaselineに記録した。各担当は現在のrootと未共有データを保持して移行待機している。定時送信も移行中だけ停止している。

公式の一般的な復旧指針でも、切断はturnの最終成否を示さないため保存状態を確認してから再送することが示されている。ただし、本件Cloudの中断原因を公式ページから特定したわけではない。
https://developers.openai.com/api/docs/guides/agents-api/errors
