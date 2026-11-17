# Recovery isolated 2: restart procedure, NOT permission to activate

Current live head read-only snapshot: ec4c8344d92c8ae390a81186218180a36ff9bfbb.
Frozen source code: e07181e8cd5926a67e588932224ab51b3ff085e1.
Source state: /tmp/x-state-recovery.json (50 + 16 accepted rows).

1. Re-read live head/state. Verify plan payload digest, fixed catalog/manifest/manual/config/validator. Verify accepted 66 rows and all existing image events. Compare Terra entries and other handoffs.
2. Stop concurrent Koyo writers. Preserve Terra stop/assignments, including expired leases and unshared results. Do not launch the recovered ops-r5 worker directly: it is Terra-oriented and cannot replace missing Koyo index code.
3. Create a NEW migration/activation record with its own revision and code digest. Current activation() produces isolated-only candidate, not production approval. Preserve both original plan payloads, hashes, accepted rows and provenance exactly. Do not claim v8 hashes match replacement code.
4. Bind new implementation to explicit reviewed CAS writer, only dispatch-index and intended Koyo namespace. Verify parent is expected live head. Do not blindly retry writes. Read back candidate commit/state hash after ACK failure. Never issue body/search request after lost ACK even if reservation committed; investigate ambiguity instead.
5. Resume at first unaccepted post, currently 2096015385070039138. Before ANY body request, check all durable context/reservation/operation records. Missing context alone is not independent proof no old request happened. Existing implementation ordering and all pending workers must be verified. Uncertainty blocks body repeat, not the entire queue; classification may use already-recorded data under unchanged procedure.
6. Real image files must match pinned manifest hashes AND an actual image-view tool must produce per-post view evidence. Hash, decode or filename is never substitute. Then validate the full row using pinned schema and plan-derived provenance, including durable body cache, exploration seal and accepted-row immutability.
7. Existing sealed v2 clocks are kept unchanged. Existing unsealed/ambiguous clocks cannot be reset. New clock tested here excludes request-to-ACK and management wait interval unions once, enforces 60 active seconds/2 searches/3 pages, and tracks wall time separately. Its equivalence to missing v8 still needs review; do not silently alter research time semantics. New clock seal-to-legacy row integration remains explicit pending migration.
8. Run one isolated end-to-end production-shaped transition using real per-post image evidence and recorded body fixture, with zero live body queries and zero live writes. Independent review before actual activation.
9. After approved activation, one live checkpoint should verify CAS acceptance and preservation digests before continued 50-post operation. New batch claiming requires its own history/unshared-work audit; not implemented by this recovery prototype.

Limitations still blocking unattended live restart:
- Real network transport, durable restart journal and body/search adapters are deliberately not connected.
- New-revision activation submission and lease renewal writer are not implemented.
- Generic LocalGitTransport CAS was tested, but production retry/connection errors and ambiguous ancestry are not integration-tested.
- Viewer receipt authenticity is a trusted orchestration boundary; code alone cannot attest that an AI saw pixels.
- New clock migration/integration and behavioral equivalence to v8 require review.

## Candidate 3 update
network_runtime.py now implements the allowlisted network Git writer (off by default), exact-candidate non-force push, current-head/content ACK reconciliation, bounded transport retry and namespace preservation. Tested against local bare remotes, never GitHub write. Lease renewal and fenced own-Koyo expired-lease reacquisition builders now exist. Durable context reservations/ACKs/seals use existing-shaped records; query lists consume each query before invocation. See CLOCK_EVIDENCE.md: wait-exclusion mode remains unresolved for multiple-search cases and must not silently revert to old wall behavior.

Remaining rollout gates: independently review the new code; connect reviewed activation and actual image/body orchestration; attest old Koyo writers stopped before fenced reacquisition; decide clock behavior from approved later specification rather than inference. Live write flag must remain false during these checks.

## Connected rehearsal update
rehearsal_pipeline.py now integrates activation verification, an OS-held Koyo lock, remote reservation before body-dispatch journal, pinned real HTTP adapter (not invoked), per-post actual image receipt, immutable save and replay refusal. RecoverySession explicitly refuses live remotes until final review/activation. An isolated local fixture replayed one ALREADY accepted post using its recorded body cache and a freshly displayed actual image from the SHA-verified bundle; resulting 66 rows exactly equal original accepted rows. Do not mistake fixture removal/reinsertion for new live classification or progress.

Independent review fixes are enforced at publish itself: typed operation+old token; normal writes require unexpired unchanged lease; renewal/reacquisition validated including fencing; body cache requires prior committed reservation; persistent last-event clock prevents reservation before an already-ACKed time; old ACKs immutable. Live writes additionally require reviewed activation with pinned recovery modules. New negative regressions cover the three reported bypasses.

## Prioritized rollout plan: resume prod-0002, not new-batch claiming
1. Complete independent review of current hashes and typed writer, then prepare explicit reviewed activation. Current live session/write gates remain OFF; no amount of passing isolated tests silently enables them.
2. Verify previous Koyo writers stopped, compare latest remote head, preserve 50+16 accepted results, and obtain a fenced new lease for the existing Koyo prod-0002 namespace only. Expired Terra assignments must never be reclaimed by this recovery path.
3. Reconcile the first unaccepted post 2096015385070039138 before any body attempt. Missing remote cache alone is insufficient proof; unresolved dispatch ambiguity must not cause a second request.
4. Process remaining pinned posts independently under unchanged visual/body rules. If there are genuinely no leads, finish with no_leads and zero external searches/pages/elapsed. Do not fabricate no_leads just to bypass the clock problem.
5. If real evidence requires additional external search and no approved clock semantics are yet available, leave that post UNACCEPTED with a distinct local operational hold. Do not replace its research labels with technical_failure, no_leads or completed merely because runtime review is pending. Preserve already-viewed images/body cache. Continue a different unaccepted pinned post only if its own history is safe. No search reservation or HTTP request should be made for the held post.
6. Holds are operational bookkeeping, not study exclusions and not accepted rows. Report accepted and held separately; prod-0002 is not complete until all required posts have a valid terminal research disposition under the original rules.
7. Do not claim a new 50-post batch while prod-0002 remains unresolved unless separately approved dispatch semantics permit that without abandoning its work. New-batch eligibility/history/unshared-work/claim logic is a distinct not-yet-implemented recovery component. User's standing authorization permits eligible next batches, but does not make an unverified batch eligible.

Normal exploration regression now includes actual isolated writer commits for two-query reserve → search ACK → page reserve → page ACK → seal. Request queries are separate from budget query history (budget_queries), avoiding a name collision. Old historical reservation records remain unchanged.
