# prod-0284 status

- Worker: terra-prod-09
- Checkpoint: e87dad9fdf183aa1ebbd55a076f933c794cd32ee
- Remote accepted: 31 of 50 posts.
- Three consecutive individual post text fetches returned HTTP 404: 2097029277254660216, 2097029514127970804, 2097029765186371751. Each was recorded as technical_failure and image-observed attributes were saved. No body refetch was attempted.
- Paused after checkpoint under the ops-r2 rule for three consecutive technical failures; systemic cause is not established. Resume from remaining posts after the technical issue is assessed.

- Resumed: subsequent post 2097030013262745970 text fetch succeeded. Checkpoint f1f7a13f14c42e5badfe57a572d1c37b165f12e3; accepted count 32.
- Audit question (accepted, unchanged): 2097030013262745970, entity_kind / animal_count: the depicted cat-like character may be a robot character; this may affect the entity classification and count.

- Checkpoint 276d495c2920f3d635b37b1fb55db3d15fe0738c: 37 accepted, 1 deferred. Post 2097030521209667737 is deferred for needs_quality_review due to many small repeated depictions whose complete correspondence could not be reliably recorded. Deferred is not complete.

- Post 2097030777536131179: image viewed, draft observations retained; context sync hit temporary Git fetch failure and the worker gate remained busy. Waiting for the fixed gate lease and grace period before retry.

- Context synchronization recovered; checkpoint fddecb044d4de38cad0e0772e031edb9b53a955b: 44 accepted, 1 deferred, 5 ordinary posts remaining.

- Checkpoint bf481375cc6473182eb5563da2270251d52064b9: 49 accepted and 1 deferred. Finish returned a transient Git fetch failure; result remains pending confirmation via the fixed CLI.

- Finish confirmed needs_review, head 81963ee4063647518d47f658b544225cd089da72; 49 accepted and 1 deferred, not complete.
