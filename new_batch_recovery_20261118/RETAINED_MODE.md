# Retain unresolved responsibility and work on another fixed 50
This new mode follows the user's latest explicit direction to record unresolved
items and proceed with disjoint work. It supersedes any universal all50-complete
gate in NEXT_BATCH_GATES.md. Complete-then-claim remains a separate mode.

## Exact transition
prepare(..., mode='retain-unresolved-and-claim', retention=receipt)
- Preserve old handoff entirely, including status leased, lease owner/token/until,
  accepted rows, body history, exploratory reservations and image evidence.
- Preserve old dispatch entry entirely. Do NOT mark it completed/failed.
- Add separate koyo_retained_work[old_plan_key] with exact all50 reserved IDs,
  exact handoff hash, and every unresolved post's reason/context/events hashes.
- Research disposition stays null. Holds are operational, never research labels.
- Hold17 uncertainty is retained; body_replay_allowed is false.
- Claim only pristine untouched catalog50 outside every existing handoff's IDs.
- New plan uses unique lease token and copied pinned provenance. Only chosen
  entry pending -> needs_review and new handoff addition are permitted.
- Whole candidate replay/CAS ensures old owner, Terra and all previous work stay
  exact. Existing source entries remain unavailable to standard Terra selection.

## Execution scheduling and mandatory live integration
The first implementation supports fenced handoff, not simultaneous old/new
writers. The prior writer must stop at a safe durable boundary and supply fresh
fencing evidence. Its lease is NOT erased, extended or stolen. Responsibility
persists in the retained ledger even after that lease expires.
require_scheduler_permission rejects body/write work on a retained plan.
This guard MUST be integrated into every affected writer publication and body
dispatch path and pinned in activation before real use. Current production
writer does not yet call it, so this candidate remains offline, live_publish
always refuses, and the artifact alone never authorizes a claim.
A later explicit resume transaction must reconcile pending body/ACK/journals,
revalidate ownership/fencing, renew/reacquire legitimately, and switch scheduler
permission by CAS. It must not remove the retained plan's duplicate exclusion.

Inventory pending_journals/unshared_work fields refer to the NEW target batch;
old unresolved durable history is expected and remains unchanged, not erased.
The retention receipt separately attests prior-writer stop and exact old-state
hash. Lost-ACK old operations must be reconciled before that stop attestation.
Full remote history/branch and all relevant local-store coverage requirements
still apply to the new target; user authorization is already supplied.

## Tests
12 discovered tests passed (includes imported repeated regression tests).
New tests show the real incomplete snapshot can prepare disjoint work WITHOUT
changing old handoff/lease/status/entry, retained scheduler blocks old and permits
new key, and 11 corrupted retention variants plus old-lease tampering are denied.
No production writes/body requests occur. Tests' fencing receipts are fixtures,
not operational evidence.
