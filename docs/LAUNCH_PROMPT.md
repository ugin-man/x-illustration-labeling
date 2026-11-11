# 最初のTerra担当に渡すプロンプト（起動用・未実行）

環境: x-illustration-labeling

モデル: gpt-6.1-terra / reasoning effort: high

---

このチャットはイラスト卒論のCloud実機確認担当です。分類本処理は開始しません。
最初にリポジトリのAGENTS.md、docs/OPERATIONS.md、docs/WORKER.mdを読んでください。
必要ならリポジトリmainを通常のfast-forwardで更新し、使用commit SHAを記録してください。

1. ローカル画像をモデルへ表示できるツールの有無を確認する。
   fixtures/vision-probe.pngを実際にそのツールで見て、表示文字と図形の色・位置を答える。
   OCRやファイル解析で答えを取り出さない。ツールがない場合は停止して報告する。
2. python -m pipeline.preflight で非公開Releaseの取得・入力hash検査を実行する。
3. python -m pipeline.probe_queue で合成データだけのGit予約・checkpoint・完了・別object storeからの回収を確認する。
4. preflightが表示した3投稿分の画像をモデルへ表示できることを確認する。
   この段階では研究ラベルを保存せず、画像数・画像ツールの成否・表示にかかった時間だけを記録する。
5. 利用可能な本文取得と外部検索ツールを確認する。大量取得はしない。

GitやReleaseの認証失敗を、画像不明や一次創作へ置き換えない。
新しい認証情報の発行、別チャットの作成、研究jobのclaim、全件分類は行わない。
環境に既存のGitHub連携が使えればそれを使い、秘密値をチャットやログへ出力しない。

最後に、使用commit、実モデル設定、各確認の成否、未解決点、synthetic probeのGit headだけを短く報告する。
統括がこの結果を確認してから、次のパイロット担当を開始する。
