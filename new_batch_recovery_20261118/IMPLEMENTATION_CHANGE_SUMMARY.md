# Changed files, isolated candidate only

Runtime changes relative to koyo-claim-connected-candidate:
- new_batch_scope.py (new): pristine accepted fixed50 activation builder; exact separate scope; startup integrity gate; source isolation/disposition pins; refusal guard.
- new_batch_images.py (new): fresh read -> policy/catalog/byte/workspace audit -> fresh read; no pixel observation or synthetic receipts.
- policy_tombstones.py (new): local+remote same-post/same-hash execution stop, metadata only.
- network_runtime.py: preserve original prod2 scope; add new exact scope and metadata exclusion; existing finalize replay, CAS, lease and immutable tests retained.
- connector_bridge.py: newscope startup/baseline pins, next-images, bundle-root binding, pre-body refusal check, record-exclusion and exclude-post.
- runtime_components.py: fixed disposition validator for metadata-only exclusions (no invented image events/body).
- next_batch.py: validated exclusions are terminal before ordinary body/clock completeness checks.
- connector_transport.js: latest live diagnostics retained; only typed exclude-post route added, same root allowlist/expected-head CAS/readback.

Exploration subdirectory changes relative to koyo-claim-exploration-guard-candidate:
- new_batch_guard.py (new): separately named exact new plan/job50 scope and refusal guard; old prod2 scope unchanged.
- policy_tombstones.py (same new shared implementation).
- prepare_live_activation.py: build_new_batch(...,authority_store,refusal_store) returns dedicated activation/config, no automatic installation.
- host_cli.py: explicitly select new guard only for new dedicated mode; legacy mode remains old guard.
- protocol_bridge.py: mandatory pin for imported new guard.
- Existing host, bounded transport, SQLite authority, one-shot search/page, seal/row machinery unchanged.

Tests are synthetic local fixtures, not classification output. No new activation/authority DB, remote write, body/search request or image display performed by this review. Do not deploy fixture JSON or old state from this directory. No current live files were edited.
