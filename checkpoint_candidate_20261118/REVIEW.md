# Offline checkpoint candidate, 2026-11-18

NOT DEPLOYED. No GitHub writes, production activation changes, live journal changes,
classification, external lookup, or new body fetch was performed by this candidate.

## Implemented
`checkpoint.py` composes up to 5 completed post deltas (finalize-post or save-row)
into one candidate from fresh state. Every member goes through an injected existing
single-post validator independently against that fresh state. Target dependencies,
plan identity, lease owner/token/expiry, paused scopes, immutable reservations,
exact row identity and unrelated fields are checked. Due policy is 5 rows or
600 seconds since oldest staged row. Local journal uses atomic replace + fsync.
Fixture-only transport implements CAS, preflight validation and exact readback.
No result grants permission to fetch. No production transport is shipped.

14 focused fixture tests and one integration test with the actual fixed row validator
and existing per-post authorization passed. Integration test uses synthetic fixtures
and a temporary bare local git repository, NOT actual viewed images or submitted rows.
Five accepted fixture rows require one fixture CAS rather than five. This is a
transfer-count result, not an observed production speedup or complete deployment.

## Required before live use
- Independently review/pin an aggregate checkpoint adapter in connector protocol,
  scope validation, bridge, transport and activation. Existing single-target protocol
  deliberately cannot send this aggregate. Do not repin ad hoc during an active writer.
- Preserve each post's acknowledged durable body reservation and one-shot journal.
  Staging results never gives another external request permit. Unknown outcomes need
  reconciliation; safety denials do not get retried as transport failures.
- Add scheduler selection of next unaccepted AND unstaged post. Current next-images
  chooses first unaccepted, so row batching without that change would revisit it.
- Maintain exploration sealed-context authority per post. Its current validator reads
  remote state; composition callback must validate independently against the same
  fresh remote base, not imaginary sequential remote states.
- On transfer failure, keep staged rows, refresh state and rebase only unchanged target
  dependencies. Accepted exact targets are skipped. Never overwrite a changed target.
- Local fsync protects process crashes, NOT deletion of the cloud filesystem. Staged
  results and consumed fetch intent need durable checkpoint/backups before reset;
  if local staged data disappears after durable body reservation, do not refetch.
- 10 minutes is an upper scheduler target, not a reliable background timer itself.
  Flush before lease expiry/handoff and on recoverable interruption; if authority is
  lost retain pending work and reconcile rather than renewing blindly.
- Record separate active view/classification, fetch, management transfer, recovery,
  idle and total elapsed spans. Current elapsed-from-first-image is not active time.

## Zero-search issue, located exactly
Ordinary `network_runtime.py` authorize_transition save-row permits only no_leads or
source_unavailable even though fixed contract includes evidence_sufficient.
Exploration `persistent_runner.py:35` requires first clock event to be reserve;
therefore initialize -> seal with no search fails. Do NOT issue unnecessary searches
or pretend evidence is no_leads to satisfy this. Correct fix is a separately reviewed
ordinary zero-search evidence_sufficient path validating actual available body,
zero counters, same-post source/provenance, fixed schema and all policy gates.
This candidate does not weaken these rules or claim to solve that path yet.

## Reduction ceiling
Row-only batching saves at most 4 of 5 row transfers. It does NOT remove each body
reservation, body cache, image-event, exploration reservation/seal etc. Finalize-post
batching can combine final result/cache/views for the non-exploration path, but prior
body reservation remains synchronous. No promise of Terra-level speed is justified.

## Follow-up implemented in isolation
- `stage_recovery.py`: content-addressed immutable stage archive with readback, restore
  by scope, conflicting-stage refusal, and unstaged selection. Any remote body attempt
  without a recovered stage is held for reconciliation, never fetched again. Test deletes
  the entire local staged copy and restores from a separate fixture directory.
  This simulates an independent durable store; it is NOT proof of cloud-reset durability
  until a same-repository archive adapter is implemented and verified remotely.
- `zero_search.py`: separate pure row-only evidence_sufficient guard. Requires existing
  available body, zero searches/pages/elapsed, no exploration clock, every applicable
  context answer directly supported by an exact body excerpt, same-post HTTPS X/Twitter
  sources, unchanged lease/scope, and mandatory policy/scope + fixed-row validators.
  Unknown context is not upgraded to sufficient. Actual semantic truth still needs
  human/model judgment; source string checks alone cannot establish attribution.
- Dynamic clock check added before fixture CAS after simulated transfer preparation,
  with configurable 120-second send margin. Tests cover preparation exceeding lease
  margin and a competing fenced owner. **GitHub CAS itself has no server-side lease
  time predicate.** This margin is a risk reduction, not a timing guarantee. Production
  must renew early, refresh/validate immediately before ref update, retain head CAS,
  and never allow a later owner to proceed without fencing via changed head/token.
  Lost/late ACK requires readback; don't promise expiry prevention by client clock alone.

Current suite: 26 tests passed. No production activation changed. The earlier 15-test
result is the baseline, superseded by this test count. The archive and zero-search
modules remain disabled for live transport and need independent review + integration.

## Independent-audit follow-up
Suite now 30 passed. `test_zero_fixed.py` executes the actual fixed contract validator,
pinned manifest/provenance and actual-view evidence checks, scheduler scope, prior
accepted baseline preservation. It accepts a synthetic direct-body case and rejects
missing view evidence / invalid schema value. This is still not a live activation.

FixtureArchive now uses fsync + atomic hard-link publication, never replacement.
A concurrent conflicting write test has exactly one winner. The production archive
still needs the GitHub immutable-object/CAS equivalent and remote readback.
`restore_available` restores independent posts while quarantining only conflicting
post versions. Timestamp-only duplicates with identical binding/result collapse;
changed results or changed lease tokens never resolve by latest-wins. Old-token
stages require explicit verified fencing/adoption review, not automatic permission.

The preserved GitHub commit 911b26ed0f28ef514245229f6c378fc87504414f contains the
26-test baseline. Later snapshots supersede it only for source, not deployment.
Transfer latency remains unmeasured in production for this candidate. Count reduction
in fake tests must not be described as measured wall-clock speed improvement.

## GitHub-shaped archive and aggregate adapters (43 tests)
`git_adapters.py` now implements the Git Data operation sequence: immutable stage
path -> tree -> commit -> expected-head CAS -> exact content readback; aggregate
writes one state.json with all existing unrelated tree entries retained. It verifies
all staged results are archived first. Source-module pin checks, exact repository and
role-specific branch checks are mandatory before each I/O. A separate reviewed live
activation is NOT present; any non-fixture transport is explicitly refused.

`local_gitdata_fixture.py` uses a genuine local bare Git repository with atomic
`git update-ref new expected-old`. The fixture persists independently of the runner,
and resetting/recreating adapters restores archived stages. No network or credentials
are used. The actual fixed validator integration now also traverses these adapters.

43 tests pass, including permission denial without retry, lost ACK before/after ref
acceptance, unavailable readback preserving outbox candidate, changed parent/head,
competing writer preservation, code-pin/destination refusal, and reset recovery.
Two tests require the preexisting frozen source-validator fixture locally; its real
state/body data is deliberately NOT in this code-only backup. Reconstitute dependencies
through the authorized research recovery workflow before rerunning those integrations.

Late expiry is tested explicitly: a GitHub-shaped CAS can arrive after client-side
lease expiry if the head has not changed. The receipt exposes
`lease_expired_after_send=true` and prohibits continuing without renewal. This is not
claimed to prevent the late write; only a backend time predicate could guarantee that.
A legitimately reacquired lease changes head/token and therefore fences the old CAS.

### Measured, but only in isolated local Git
`BENCHMARK.json` records five synthetic completed rows in a 2.6 MB padded ledger.
Single-row path: 80 API-shaped calls, 5 CAS, 13,012,130 outbound bytes, 39,018,813
response bytes. Archive+aggregate: 79 calls, 6 CAS (5 small stage archives + 1 large
checkpoint), 2,611,600 outbound bytes, 7,816,548 response bytes. About 80% fewer bytes,
but essentially no reduction in total API calls, and one additional CAS.
Local wall times are in the JSON and NOT transferable to GitHub/network performance.
These measurements exclude body/search reservations, image work and classification.
Therefore this is promising for payload-dominated delays, not proof of real speedup.
No main, production dispatch branch, live stage archive or runtime activation changed.

## Recovery and tree integrity fix (54 tests)
Recovered after runtime reset. Prior remote commit 4794dbc386092879eb85259069b0affe7b31c7fd is NOT deployment-ready: it could accept a correct state.json while losing unrelated tree files.
Before any ref update the common commit builder now checks complete recursive Git tree Merkle roots, exact path sets, unchanged non-target modes/types/blob IDs, and target UTF-8 content. Archive and aggregate share these checks. Class/role mismatch is also refused. Fault tests cover dropped base, extra files, wrong content, non-target mode/type changes, symlink targets, truncated listings and archive preservation. Independent execution after recovery: 54 tests passed. Live adapter remains disabled. Updated benchmark supersedes earlier counts and still does not measure GitHub latency.
