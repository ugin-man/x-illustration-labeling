# Isolated connection only. Production writes explicitly stopped.
No live files/activation, remote state, body fetch or actual claims were changed.
Do not deploy or invoke CLI against production while the explicit safety stop
remains. This artifact is independent code/testing/review, not an alternate send.

## Implemented boundaries
- ClaimWriter accepts only an exact reviewed candidate, before hash and dedicated
  reviewed-live-claim activation with mandatory module hashes. No CLI push.
- Canonical existing connector protocol constructs one tree/commit, revalidates
  current head/lease immediately before expected_sha CAS, then full readback.
- claim_cli/claim_transport are separate from ordinary operations; receipt never
  grants body execution. A new batch still needs a separately reviewed labeling
  activation before any work. Existing current32 activation is NOT widened.
- Normal IndexWriter authorization AND preservation reject retained-paused keys.
- connector_bridge fetch-body and RecoverySession.body_once check the scheduler
  on freshly read state BEFORE returning cached data or performing body dispatch.
- Exploration separate-copy central ReviewedClockGuard also rejects paused keys;
  host prepare/write/external claim paths all call this guard.
- Claim retains old handoff including lease/status exactly and separately records
  unresolved responsibility. No completion/failure labels or body replay.
- Subsequent retained batches are allowed only if prior retained ledger exactly
  matches the frozen handoff and has one matching accepted successor plan.
- complete() now validates projected cache shape and rejects any unsealed clock,
  including clock-without-budget. Legacy accepted completed baseline exception
  remains exact-hash bounded and cannot admit new incomplete clocks.

## Actual evidence collection
collect_environment walks explicitly specified roots without following symlinks,
hashes files, reports target-ID/job matches, missing paths/read errors/symlinks and
observed relevant writer processes. assemble requires separately reviewed
exhaustive environment/root coverage, one fresh observation for EVERY environment,
and fresh independently verified remote branch absence. Missing evidence never
becomes an empty unshared-work report. Known broad metadata may produce false
positive matches; this is conservative, not grounds to hide or delete files.
No real coverage/zero-work assertion has been made. E2E inventory is MOCK ONLY.
Full ancestry collect_local_history still needs verified fetched source history.
Inventory and history raw evidence require independent provenance review;
an arbitrary caller-supplied JSON assertion is NOT trusted production evidence.

## Integration before any later authorization
Compare with newer live code and exploration/diagnostic candidates, preserve their
reviewed changes, update ALL mandatory code pins (including next_batch).
Do not copy old fixtures, state or activation. Confirm prior writer fencing,
resolve uncertain transport outcomes and pending dispatches before claiming.
Current source root, path allowlists and connector CAS destination unchanged.

## Tests
Focused inventory unknown/dirty rejection, mock local Git connector E2E with
expected-head CAS/readback, paused normal writer/body rejection, malformed cache/
unsealed-clock rejection and repeated retained-successor regression succeed.
Claim JS success/split/error/lost ACK/cross-post refusal succeed (5 cases).
Exploration paused guard test succeeds. Full regression results in logs.
