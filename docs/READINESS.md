# 準備状態（2026-11-11）

**2026-11-12更新：人間の事前確認は完了。除外30投稿の隔離完了後、Terra 1担当で新100投稿を実施する指示あり。本番全件は未許可。**

除外適用済みの新入力は20,728投稿・26,581画像参照。原本をローカルの作業フォルダ外へ移し、除外ポリシーのhash固定と展開前/表示パス返却前の検査を追加した。ローカルテストは54件、53成功・旧実ZIPテスト1件skip（旧ZIP隔離による）。GitHub側の旧配布ZIP除去が済むまではlaunch-controlをblockedに保つ。下の記述は以前の準備履歴。

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
