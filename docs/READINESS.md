# 準備状態（2026-11-11）

- 非公開GitHubリポジトリ作成済み。
- data-v1 Release: 416画像バッチ + catalog.json = 417ファイル、8,687,367,370 bytes。
- 入力20,758投稿・26,612画像参照・26,357画像ファイル。全画像のSHA-256を元DBと照合済み。
- 調整100/評価100/本処理20,558投稿を分離。同一画像が調整/評価に跨がらない。
- Python標準ライブラリだけで動作する予約・保存・復元・検証・集約CLIを実装。
- ローカル12テスト成功。8並列予約の勝者1、期限切れ・古い担当拒否・回答衝突・ZIPパス検査・全画像対応・unknown集約・実ZIPを通した模擬出力回収を確認。
- 実投稿1件でFxTwitter v2本文取得に成功。人気指標は投影時に破棄。
- 人手回答と既存除外判断はprivate/へ隔離し、元DBは変更していない。

この時点ではTerra分類担当を起動していない。Cloud内の画像ツール、Git push、非公開Release取得は最初の実機probeで検証する。Cloudの利用枠と実効速度、分類精度も未計測。環境セットアップの結果は後続の準備記録へ追記する。

参照： [Cloud環境](https://learn.chatgpt.com/docs/environments/cloud-environments)、[Codex利用枠](https://learn.chatgpt.com/docs/pricing)、[GitHub上限](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)、[Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)、[FxTwitter API](https://docs.fxembed.com/api/twitter/operations/2statusid/)。
