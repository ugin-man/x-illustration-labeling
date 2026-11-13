# ops-r2 の切替記録

2026-11-13。ユーザーの運用修正・全担当と毎時送信係への周知依頼に基づき適用した。

## 適用済み

- 固定分類run: production-v4-001。元commit 4d2c98374a1364faf1e2b546a4c460e80e9b2903 の分類manual/schema/toolchainは不変。
- 運用追加commit: 1380ac4e9120ce8babef9241b5764cccc8209d34
- 全10担当の停止・保存、追加7ファイル導入、新マニュアル全文読了、hash/contract確認を実施。
- 全員の確認後に有効化commit 5a00e8ba646396fb15d28a5144c64d9155dfeca2 を公開。
- 新manifest SHA256: 3f7aaa36c1c6badd21c8a232456ebc18c18e235623cf82486b1df20812f75068
- enabled control SHA256: 0f8761de4b1ddcdb36202297c299cb8dcfd143e59043124964bdec97645624b8
- 全10担当へ改訂CLIでの独立継続を指示。10人が異なる10jobを所有し、再開後のremote更新を確認。
- 毎時送信係へ変更理由・変更箇所・役割維持を通知。既存automation 10を新定型文でACTIVEへ戻し、毎時・送信のみの設定を照合。

## 運用変更

未受理の自分の誤記を元データ保全付きreviseで修正できる。1投稿の判断待ちはdeferで未完了のまま保存し、他の通常投稿を進める。context/cache・探索予算はremoteへ永続保存・復元する。受理済み回答、分類項目、探索上限、人間除外30投稿・拒否の扱いは変更しない。

## 検証

- 全suite: 130件実行、OK、環境依存1件skip。
- 最終的な共有画像の連鎖保留修正後: 関連23件を再実行し全成功。
- Terra 01の実機確認: prod-0078 / post 2095145739475366195。隔離監査は除外一致0。CLI返却パスに対応する実imageViewイベント確認後、save/checkpoint成功。
- 受理42→43。旧42回答のblobが全て不変であることをGitHubから独立照合。
- 初回claimからcheckpoint応答551.186秒。draft前356.444秒（初回移行・隔離・準備）、draft開始からcheckpoint194.742秒。1投稿で通常速度や意味内容の精度を保証しない。

## 保留の扱い

prod-0149の2095884922972193015、prod-0298の2097120133303226795はapproval_requiredのdeferを保存。画像の再表示や拒否されたexclude操作の再試行はしていない。既存受理33件・0件を維持して残りの通常投稿を処理可能に戻した。2投稿を完了件数へ加えていない。

詳細は review/production-v4-001-ops-r2-rollout.json と検証receiptを参照。試験時点の本番受理は3,827/20,628であり、全量完了ではない。
