# 統括用の運用手順

**最優先の例外：画像確認・解析でポリシー拒否が出たら、その投稿全体をCLIのexcludeで即時に暫定除外し、作業可能なら次の別投稿へ進む。個別の確認待ちや仕事全体のholdにはしない。同じ画像の再表示・再送・加工・言い換え・モデル切替で再試行しない。セッション全体の停止は突破しない。手順はdocs/WORKER.md冒頭。**

人間の事前確認は完了。ユーザーは除外30投稿の隔離完了後、Terra 1担当で新ルール100投稿を試すよう指示した。本番全件は未許可。隔離の完了確認まではlaunch-controlをblockedに保つ。既存100投稿の結果とv2の固定ファイルは保持する。人間用の一覧や保存DBをAI担当のテストに使わない。

## 確認完了後の入力準備

1. ローカルscreening DBがcompleteか確認し、ユーザーの別の開始指示を得る。完了ボタン単独を起動指示と解釈しない。
2. `python -m pipeline.prepare_screened` で除外を取り除いた新規ZIPを作る。既存data-v1を流用せず、direct除外した全画像と同じハッシュを含む投稿も対象外とする。
3. `dist/data-v3-RECEIPT/` と `data/catalogs/data-v3-RECEIPT.json` が版固定の入力。`data/catalog-v3.json` は最新準備版の案内。人間の確認が途中で変われば再作成を要する。
4. 新しい専用の非公開Releaseにこの版のZIPだけを配置する。今回の100投稿試行ではrunの2バッチのみ配布する。assetsの対応表は `data/assets/DATASET_VERSION.json` に保存し、name/size/asset IDを照合する。秘密値や画像をmainへ入れない。新担当のセットアップで旧Release全体を取得しない。
5. `python -m pipeline.prepare_run RUN --split calibration` で新runを固定する。空のsplitは拒否。catalog/manual/schema/ツール/担当手順をhash固定する。改訂後は別runを作り、旧configへ新しいhashを上書きしない。
6. 明示された開始範囲だけを `data/launch-control.json` に固定する。state=authorized、authorized_run_id、catalog_sha256、screening_receipt_sha256、authorization_noteが必要。自動作成・自動許可は行わない。

事前除外の隔離：元アーカイブと旧data-v1はローカルの作業フォルダ外へ移す。人間用アプリだけがignoredのprivate/human-source.jsonから原本場所を参照する。GitHub旧Releaseの除外画像入り28ZIPはローカル原本のハッシュ検証後に配布から除去し、asset IDの消失を確認する。ブラウザ経由で復元不能な削除を実行する場合は当該ツールの実行直前確認に従う。除外メタデータはrunにhash固定し、catalog、展開前manifest、nextが返す実ファイルで照合する。Cloudでは実画像表示前にworkspace内の残存をバイト検査する。除外画像を検査のためにモデル表示しない。

コードだけの準備テストはPython 3.10+とGitで実行でき、外部サービス・パッケージ・実際の画像判定を必要としない。

```sh
python -m unittest discover -s tests -v
python -m pipeline.worker contract
```

ローカルで確認結果が変わると旧許可を拒否する。配布済みCloud VMはこのPCのDBを参照できないため、クラウド開始後の変更は旧runを明示停止し、新入力・新runで再開する。遠隔の古いcheckoutまでローカル変更が瞬時に届く仕組みではない。

## 自主予約と中断

仕事ごとに `codex/jobs/RUN/JOB` の独立ブランチを使う。固有root commitの通常pushで最初の予約を競合させ、更新は読んだheadの子commitだけをpushする。force pushは使わない。予約60分、期限後2分猶予、新担当は別token。受理済み結果の上書き・二重採用を防ぐ。

saveはローカル保存で毎投稿のGit通信は不要。checkpointで遠隔token/期限を確認し、成功後にローカル期限も更新する。未送信の計算はクラッシュ後にやり直す場合がある。20担当などの同時checkpointは時刻を分散する。多並列時の速度・サービス制限はまだ実測していない。

| 状況 | 処置 |
|---|---|
| no_available_job | 担当を終了。空ループを回さない |
| lease期限切れ | ローカルファイルを保持して停止/再予約。期限を書き換えない |
| 受理済み回答と相違 | 既存回答を保持。新review runで裁定 |
| モデル/画像ツールのポリシー拒否 | 当該投稿をexcludeで暫定除外、直ちに遠隔保存して次の投稿へ。画像を再送しない |
| 単独入力に事前確認が必要 | holdで有効な途中結果を保存し、仕事をneeds_reviewへ。自動再予約しない |
| 本文/検索取得不能 | technical_failure。originalへ変換しない |
| 検索後も根拠なし | complete/unknown。全unknownを手動holdへ回さない |
| 通信・利用枠の問題 | 可能ならcheckpoint/release、ファイルを保持して報告。新担当を無限に増やさない |
| schema/マニュアル変更 | 新版・新run。凍結済みの結果を新ルールに見せかけない |

## 集約と評価

```sh
python -m pipeline.collect --config runs/RUN.json --output .runtime/collected/RUN
```

完了jobだけをmanifest/hash/schema/来歴の検査後に集約する。holdしたjobの途中結果はjob内に保持され、最終完成表には混ぜない。未完了job数をreceiptで残す。

v3出力は labels.jsonl、posts.csv、images.csv、characters.csv、appearances.csv、quality-profile.json、review_queue.jsonl、exclusions.jsonl/csv、receipt.json。暫定除外は分類結果の表に混ぜず、exclusionsへ最小限のメタデータだけを出す。receiptのprocessed_postsは分類済み、excluded_postsは暫定除外、resolved_postsは両者の合計。除外をfalse/unknownや視覚処理成功に置き換えない。charactersのIDは投稿内だけで一意。複数投稿に同じ作品キャラがいても人物同定は行わない。

完了jobの内部アーカイブ名labels.jsonlは互換のため維持し、そこには通常ラベルと明示的なrecord_type=exclusionを保存する。分析には必ずcollectの出力を使う。除外は収集時に分離される。暫定除外は人間のscreening DBを上書きせず、runの処理記録として保持する。自動解除・自動再投入はしない。

比較単位は投稿（いいね等の結果1件）を基本にする。画像数・人物数分だけ同じ人気指標を複製して独立標本と見なさない。髪色フラグはtrueが1枚でもあればtrue、全画像で確実にfalseならfalse、それ以外はunknown。欠測をfalseへ変換しない。

最初の新仕様の小規模実測では、キャラ数、髪色の陽性/陰性/unknown、画像形式、由来を別々に確認する。調整用と未使用評価用を混ぜず、判別しやすい例だけの正解率を出さない。人間が先に除外した範囲・件数は研究対象範囲として記録する。成人向けを除いた結果を元の全投稿全体へそのまま一般化しない。

quality-profileは不明率と分布を示すだけで精度ではない。無作為2%の確認候補と、技術失敗・review_flagsの対象は別に出す。統括が全件を再分類する必要はない。新仕様の精度・所要時間・予算・並列数は、この構造テストだけでは決めない。
