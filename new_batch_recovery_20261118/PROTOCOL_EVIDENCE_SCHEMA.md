# never-assigned-protocol-v1 (isolated candidate, not live activated)

This is a second, explicitly typed eligibility proof. It does NOT populate disk inventory arrays with empty values and does not assert physical disks were scanned. Old claim_inventory.assemble remains unchanged.

Conclusion: no prior authorized assignment for this fixed target under the independently reviewed atomic production protocol. physical_store_coverage is always 'unconfirmed-not-used-as-zero'. Known previous assignments, target intersecting any worker's known responsibility, missing coverage, changed source artifacts or contradictions refuse.

## Required bundle
- schema: never-assigned-protocol-v1
- history: exact collector output for current source_head, candidate job, complete ancestry, ever_touched=false, count and digest. It must byte-semantically equal the JSON artifact referenced by review.history_source_sha256.
- artifacts: actual original source files [{path,sha256,source_kind,source_reference}], every file hash rechecked. Source kind limited to thread_management/github/pinned_source/saved_management_record. No secret or unrelated files; these remain local and are not copied into state.json.
- review: reference, actual run_id/catalog hash, true initial index root, current source tip commit, explicit reviewed continuity/atomic-before-local/out-of-band coverage. Role-specific history_source_sha256, protocol_source_sha256, mapping_source_sha256 plus hash of artifact list.
- protocol review artifact: candidate/root/root_scope_matches/source_commit, reviewed_revision_commits, required_deployed_revision_commits, initial_production_commit. Required revision set is independently determined from real rollout/ready records and source ancestry, not selected to satisfy a check.
- reviewed_code_revisions: EXACT required set with no duplicates. Each commit has code_review_sha256 artifact which includes it in reviewed_revision_commits. Initial-production entry is bound to root and initial code commit evidence; ops-ready entries have launch_source_sha256 pointing to original ready JSON with matching candidate and all ten worker IDs.
- worker_thread_mapping: exact ten-worker map equal to original mapping artifact's worker_chat_states. Ten unique thread IDs required.
- workers: ten latest read receipts, explicit stopped assessment, last_job_id, known_unshared_jobs, source_sha256, stop_message_id/hash. Raw artifact must contain matching threadId, completed latestTurn, exact untruncated assistant message/job. Freshness is derived from original artifact retrieved_at, not caller timestamp. Observations must be within300 seconds at final gate.
- refs: actual current index head, exact target job branch absence, verified remote reference, observation within60 seconds.
- known_contradictions must be empty. This means no contradictory evidence after review, not universal proof of unknowable out-of-band actions.

## Integration
next_batch.prepare recognizes only the explicit evidence_mode and validates its summary without accepting fabricated unshared_work/active_writers/pending_journals arrays. ClaimWriter reconstructs the summary from full local source bundle and compares ALL summary fields except refreshed checked_at to the candidate. It additionally requires protocol_claim_evidence.py pinned in the exact claim activation. Original full candidate replay, old responsibility preservation, lease, freshness, expected-head CAS and ACK/readback remain unchanged.

## Actual evidence status
The evidence collector found candidate prod-0281 pristine in7114 ancestors, root9879e9641e1300aab5ae2ea3b27c55f59859be9a. All ten latest stopped reports are for different jobs; physical Terra stores remain unconfirmed. Atomic reservation-before-local-work was inspected across production and ops r2-r5 source ancestry, with saved baseline anchors. These facts are sufficient for the bounded inference once all artifacts/coverage lists are independently reviewed and refreshed. They are NOT filesystem absence proof, universal no-reset proof, or a new user permission.

Before use: stop current Koyo writer at durable boundary, freeze exact head; regenerate/extend history proof if head changed; refresh ten latest thread reads and exact branch absence; assemble the role-bound bundle; independent review; prepare and publish once using dedicated activation. Do not reuse stale timestamps or alter proof types to pass. Transport denial/uncertain ACK stops as before.

Final binding correction: refs_source_sha256 must refer to the actual remote-observation artifact. Exact head/candidate/empty ls-remote/branch reference/observation timestamp must agree; fresh timestamps cannot be invented separately. Missing deployed revision, source hash mismatch, forged stop message, duplicate/missing worker, target-known-unshared, stale refs and disk-zero masquerade are negative cases.

Independent audit found and verified fixes for role-bound original artifacts, exact full deployed revision coverage (including initial), and full summary comparison. No remaining code Blocking in inspected scope. Actual protocol review artifact must contain initial_production_commit/required_deployed_revision_commits/reviewed_revision_commits before a real bundle can pass; old artifacts are not grandfathered.
