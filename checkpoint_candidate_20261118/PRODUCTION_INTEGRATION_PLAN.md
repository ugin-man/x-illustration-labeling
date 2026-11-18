# Isolated rollout proposal and integration delta

No production activation or production data was changed. `integration_driver.py` is live-disabled and refuses non-fixture transports. It accepts the currently assigned handoff's original scope activation; it does not claim a new batch, renew a lease, or issue any body-fetch permission.

## Implemented in isolation
- Pin existing plan identity, scope activation, accepted baseline rows and mandatory candidate modules.
- Validate each completed result with the actual IndexWriter transition/preservation logic and the actual pinned schema/source/view checks.
- For ordinary evidence_sufficient with no exploration, use the separately reviewed direct-text route plus unchanged new_batch_scope validation, source pins and policy tombstones. Never fabricate a search or relabel as no_leads.
- Archive completed results before treating them as durable.
- On restart, retrieve archive, verify stages against fresh head/state/scope/lease; quarantine conflicts and old tokens rather than automatically adopting them.
- Selection excludes accepted and staged posts. A body attempt without recoverable stage is held for reconciliation, never fetched a second time.
- Checkpoint at five posts or ten minutes, and at explicit safe handoff/end. Before publish use all existing CAS/tree/readback protections.

Eight added integration scenarios pass. They use synthetic manifests and source fixtures only. The isolated archive uses real bare Git independently of the worker object; recreation verifies resume without a local stage list. Existing network v2 tests separately exercise the same unchanged research validators in a synthetic-only closed transport. Neither is a live deployment.

## Proposed production insertion points
1. Sole current writer finishes/records the active operation and proves no uncertain publish remains. Record accepted head, pending body/row journal and exact token; do not change Terra or retained prior work.
2. Verify candidate code pins and independently reviewed activation diff. Existing activation must be formally updated through its normal protocol, not edited to pretend unchanged pins.
3. Introduce typed completed-stage and checkpoint operations into the existing connector bridge. Do not expose generic update_ref, arbitrary branches or arbitrary tree writes as worker methods.
4. Use an explicit same-repository archive branch and only completed-result namespaces. All source/body scopes remain the existing task's authorized data. Readback must prove stage durability.
5. Hook the current next-post selection to restore_and_select. Resume incomplete acquisition only through original reconciliation, not through checkpoint selection.
6. Preserve original ordinary/exploration separation. A sealed exploration result must carry the existing budget and receipts; an unsealed result cannot be staged as complete.
7. Renew early through the existing normal lease workflow. A changed token requires explicit fencing/adoption review for old stages. CAS cannot impose server-side time expiry.
8. Start a new measurement segment at the first actual production operation using new code. Label the previous 50-post segment as old save cadence; do not overwrite its elapsed history.

## Performance finding and next measurement
The earlier measured local five-row test reduces large-ledger bytes by about 80%, but adds one CAS and does not lower total API calls. Therefore it has not proved the production speedup requested by the user. Final pinned network v2 proves successful operation only, not a comparable baseline/optimized timing experiment.

For production's first bounded interval, record exact operation durations, request/response bytes, accepted rows, staged rows, body failures, retrieval/exploration waits, renewal/recovery, and total elapsed wall time. Compare like-for-like save paths; do not call time since first image viewing active classification time. If per-stage archive overhead outweighs transfer savings, retain the safe old path and improve payload/roundtrips instead of declaring success.

Still required before production: closed typed transport integration with normal activation, independent review of its final pins, sole-writer boundary, and actual same-scope timing. No claim of production throughput or physical cloud-destruction recovery is made.
