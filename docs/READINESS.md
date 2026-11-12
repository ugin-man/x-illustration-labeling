# 準備・試行の状態（2026-11-12）

**除外30投稿の隔離と、新ルールのTerra 1担当・100投稿パイロットが完了。本番は未開始・未許可。**

- 旧Releaseの対象28ZIPだけを削除・照合済み。原本と30投稿→28ZIPの対応表はPCの人間用保管フォルダに残している。
- 新入力は20,728投稿。今回Cloudへ公開した画像は調整100投稿用の2ZIPだけ。Cloud残存検査も除外画像0件。
- pilot-v3-001: 100投稿・126画像が完了。欠落・重複・除外混入0件。画像ツールの実行履歴126/126を独立に照合済み。
- 初回予約→最終完了は1時間52分27秒、約53.4投稿／時。セットアップ・報告作成は含まない。
- 制作方法はデジタル4、アナログ11、判別不能111。安定した分類精度を測れたという結果ではない。
- 外部検索1投稿の上限超過、文脈取得22投稿の失敗、人気指標の偶発表示の報告を保持。本番前の改善対象。
- 新しい確認ツールは `確認ツールを開く.cmd`、既定URLは http://127.0.0.1:8766 。新結果100投稿を読込確認済み。
- 凍結した分類ルール・workerコードは変更していない。変更が必要なら別revision/runにする。

詳細は [100投稿試行の報告](../review/pilot-v3-001_report.md)。実行前のqueue/schemaテストは54件中53成功・旧ZIP隔離による1skip。人間用レビューの変更は5テストと合成データでのブラウザ動作確認を完了。

## 以下は更新前の準備履歴

過去時点の件数・状態を含む。現在の実行許可と状態は上記を参照。

# 準備状態（2026-11-11）

**2026-11-12更新：人間の事前確認は完了。除外30投稿の隔離完了後、Terra 1担当で新100投稿を実施する指示あり。本番全件は未許可。**

除外適用済みの新入力は20,728投稿・26,581画像参照。原本をローカルの作業フォルダ外へ移し、除外ポリシーのhash固定と展開前/表示パス返却前の検査を追加した。ローカルテストは54件、53成功・旧実ZIPテスト1件skip（旧ZIP隔離による）。GitHub側の対象28ZIPの削除を照合済み。原本はPC側に保存し、除外30投稿と28ZIPの対応表も作成済み。新Releaseには100投稿用の2ZIPだけを配置し、pilot-v3-001だけを許可した。Cloud側の残存監査も除外画像0件で合格。下の記述は以前の準備履歴。

- 非公開GitHubリポジトリ作成済み。
- data-v1 Release: 416画像バッチ + catalog.json = 417ファイル、8,687,367,370 bytes。
- 入力20,758投稿・26,612画像参照・26,357画像ファイル。全画像のSHA-256を元DBと照合済み。
- 調整100/評価100/本処理20,558投稿を分離。同一画像が調整/評価に跨がらない。
- Python標準ライブラリだけで動作する予約・保存・復元・検証・集約CLIを実装。
- ローカル12テスト成功。8並列予約の勝者1、期限切れ・古い担当拒否・回答衝突・ZIPパス検査・全画像対応・unknown集約・実ZIPを通した模擬出力回収を確認。
- 実投稿1件でFxTwitter v2本文取得に成功。人気指標は投影時に破棄。
- 人手回答と既存除外判断はprivate/へ隔離し、元DBは変更していない。

この時点ではTerra分類担当を起動していない。Cloud内の画像ツール、Git push、非公開Release取得は最初の実機probeで検証する。Cloudの利用枠と実効速度、分類精度も未計測。環境セットアップの結果は後続の準備記録へ追記する。

## 起動前準備完了（2026-11-12 JST）

- GitHubの417個すべてのassetで、サーバー側SHA-256とサイズがローカルと一致。
- Cloud環境 `x-illustration-labeling` を公開済み。APIでも status=ready / runnable=true を確認。
- 利用者は「自分のみ」。GitHubと画像配布先、FxTwitterの計6ドメインを追加許可。
- CloudセットアップはPython 3.12.14 / Git 2.52.0。11テスト成功、ローカルの実ZIPが必要な1テストだけskip。CLIの分類定義出力も成功。
- Windowsのローカルでは実ZIP経由の模擬回収を含む12テストが成功。
- Cloudセットアップ用チャットは作成したが、Terraによる分類担当、研究jobの予約、本番ラベル作成は未実行。
- 次はdocs/LAUNCH_PROMPT.mdをTerraの最初の1担当へ渡し、画像入力と非公開GitHubの往復を実証する。

環境ID: `312b1ef7-3bac-470c-b407-a04a838882be~asenvcfg_b082a759192481918121a4ccd78c7982`

セットアップ用チャット: `6af48216-6628-8191-8d78-bb2bc412c0a7`

ローカルGitの現在ブランチはcodex/preparation。GitHub mainと同じ内容・履歴を保持し、画像8.7GBはGit本体へ格納しない。

参照： [Cloud環境](https://learn.chatgpt.com/docs/environments/cloud-environments)、[Codex利用枠](https://learn.chatgpt.com/docs/pricing)、[GitHub上限](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)、[Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)、[FxTwitter API](https://docs.fxembed.com/api/twitter/operations/2statusid/)。
