# Successor activation proposal, NOT installed

## Evidence and limits
- Prior approved rollout precedent: the existing compressed-transport and atomic-finalize rollout documents describe reviewed code deployment at a durable boundary while retaining source/scope/baseline and updating module pins. They are a precedent, not automatic approval for this change.
- Current new_batch_scope.build only admits pristine claims. Do not call it with progress, alter genesis to pass it, or create a different batch identity.
- No typed, reviewed in-progress activation-transition generator exists in the inspected runtime. This document specifies one for independent review; it executes nothing. Existing pin checks must remain fail-closed.
- Preserve the prior activation privately, byte-for-byte. Record full-byte and payload hashes and exact old/new code hashes in a private migration manifest. Do not publish activation or state.

## Required authorization and reviews
1. Operational owner must approve the exact migration manifest after receiving code diff, fixed-validator hash, successful target7/regression94 test receipts and source-only backup commit. This is not inferred from a fixture flag or a generated review string.
2. An independent reviewer checks the migration implementation, not only the classification patch: old-to-new permitted fields, complete hash set, rollback, crash-before/after install, pending journals, state/lease drift, version rollback attacks, preservation, scope identity. Reviewer must return explicit result and concrete reference.
3. If any tool/policy calls for human approval, use that actual approval route. A local approval JSON is an evidence container only, never authority by itself. No automatic adaptation after a denial.
4. Production remains on old version until the above are complete and the coordinator explicitly releases this exact deployment. Current task authorization is plan/isolated-fixture only.

## Read-only preflight (repeat at deployment)
- Quiesce sole Koyo writer, settle all tools and CAS, inspect exact pending envelopes and body/research intents. Never reuse uncertainty as no-op evidence.
- Fetch fresh full state and head. Validate existing activation unmodified with validate_document; verify every pinned module, original fixed schema/manual/catalog/screening, original genesis-state hash and baseline_handoff equality.
- Verify current scope exact same50, job the existing job, plan hash, destination/worker koyo, scheduler not retained; no change to holds, disjoint responsibility, other workers or Terra.
- Snapshot every existing row/context/event/operation and all other namespaces. These are preservation expectations, NOT a replacement genesis baseline.
- Require a currently valid lease with sufficient margin or use the original fenced reacquisition/renewal flow before capturing final preflight. Never extend lease by editing activation.
- If body cache and image events are already durable, retain them and do not refetch. Preserve any existing exploration authority and inspect pending state; never initialize it again or synthesize research.

## Proposed generator contract (pure/local, reviewed before implementation)
Inputs: prior immutable activation, prior immutable code bundle, approved manifest and review references, verified fresh state/head, reviewed successor code bundle, original genesis snapshot, caller-provided output directory known not to be live path.
Output: new successor activation candidate plus a separate migration receipt. Never edits input activation or files, never calls connectors, never writes to live path. Refuse existing output to avoid overwriting prior evidence.
- Validate full prior document and all original pins BEFORE considering candidate code.
- Exactly one approved code change: network_runtime.py old hash -> new hash as manifest. All other code/module/safety hashes must be identical. Reject extra or missing pins, new file paths, path escapes and symlinks.
- Candidate retains mode/revision, plan_sha256, original source_head/source_state_sha256, pristine baseline_handoff/baseline_identity/baseline_rows, scope including false external_exploration, image_gate, all source provenance exactly. Do not rebase these onto current progress.
- Only candidate code_sha256 entry for that existing module changes. Review_reference may be augmented with explicit successor-deployment review reference; no other payload field changes. Separate receipt binds parent activation document+payload hash, candidate hash, exact patch/backup commit, final preflight head/state digest, unchanged-field digest, operational and independent review references. Do not add remote runtime_upgrade: it is immutable under current writer.
- Candidate must pass unchanged validate_document and validate_scope against an isolated copy whose approved paths/hashes point to that isolated bundle. Exercise original PinnedInputs and full new save-row validation there; no network. The isolation harness path substitution is test plumbing, not a production-path authorization.
- Production-path candidate is generated only after approved installation is separately authorized. Merely recomputing sha(payload) is NOT the transition or approval; generator must verify every preceding restriction and receipt.

## Isolated acceptance suite required for generator
Positive: immutable old activation remains byte-identical; exact one-module candidate; original genesis unchanged; correct current-progress preflight; nonillustration direct save-row; preserved prior rows/Terra; review evidence traceability.
Negative: arbitrary repin, unreviewed/new module, stale old hash, bad candidate hash, missing review/operational reference, altered scope/job/worker/source/baseline/refusal gate, altered schema, symlink, old code/version rollback, lease expiry, changed state/head, active concurrent writer, unresolved ACK, consumed/pending research/body intent, output live path/overwrite, attempted remote side effect. Test both interrupted installations and rollback. Existing7+94 patch tests are not substitutes for this generator suite.

## Eventual deployment sequence (NOT authorized/executed here)
1. At locked safe boundary archive old code+activation+receipt; preserve every journal, authority, current-batch-baseline and progress file. Verify source-only backup exists/readbacks.
2. Install approved code bytes and successor activation as a coordinated local version switch while writer remains stopped. Crash at partial switch must cause pin mismatch and stop; no automatic fallback or research replay.
3. Revalidate all pins and unchanged fields; reread remote state/head/lease and compare receipt. If drift, halt and redo preflight under original rules, never weaken equality.
4. For a post whose cache/events are already saved use existing connector_bridge prepare save-row, NOT finalize-post because cache/events already accepted. Follow unchanged create_tree/commit/exact fetch/pre-ref/expected-head CAS/ACK/readback. No body or research fetch.
5. Verify only the target row added and all prior state retained, then report the verified count. Subsequent normal next-images may then select the next post.

## Rollback
- Before any new remote commit: stop writer, restore archived matching old code+old activation pair atomically; validate full hash set and remote unchanged. Keep migration receipt and failed successor evidence. The target post remains blocked; do not claim completion.
- After a certain target-row save: never roll back remote rows, body history, clocks or entries. Stop writer; compatibility-test old runtime against a copy of latest state. Only restore matched old pair if reviewed compatibility succeeds; otherwise remain stopped and forward-fix. New-format state is not introduced by this patch, but that is still tested rather than assumed.
- On ambiguous CAS: no rollback that could enable replay. Reconcile exact head/state and unchanged operation receipt first. Never delete journals/authority. Code rollback does not undo an external action.

## Independent work / hold routes
- connector_bridge hold records local operational-hold.json with approved reason, not a research result. next_images explicitly has no skip list and ignores local hold, so it cannot safely expose later posts while the blocked post is first pending. Do not invent a refusal/exclusion to advance.
- Existing retain-unresolved-and-claim is a separate whole-batch fenced transition, not a same-batch skip. It preserves all old data and pauses old scheduler, but requires fresh full untouched-target history/inventory, separate claim activation/CAS, a pristine new50 and later explicit resume transaction. It would interrupt the current50 timing trial, so do not invoke it merely to dodge this implementation defect.
- Current recommendation: finish reviewing narrow successor transition, then save35 normally. Until then report the last verified count.
