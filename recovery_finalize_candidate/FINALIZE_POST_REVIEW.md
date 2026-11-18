# Atomic finalize candidate (not deployed)
Base: reviewed current-batch candidate. Live directory and network untouched.
Changed runtime: network_runtime.py, connector_bridge.py, connector_transport.js.
No compression or research/exploration scope changes.

## Flow
Keep existing body-reserve -> normal connector CAS + certain ACK -> fetch-body.
Never merge the reservation with execution or replay a staged body.
Prepare actual same-post view-receipts.json and row-final.json as before.
Instead of three publishes:
    python connector_bridge.py prepare finalize-post POST_ID
Publish its unique outbox via unchanged canonical tree/commit/CAS/readback protocol.
Accepted readback marks same-post staged cache accepted, including reconciled
uncertain ACK. It never grants another body call (fetch-body requires the
body-reserve operation and absent dispatch journal).
Scope activation must pin all changed modules and retain original baseline17.
Do not rebuild baseline from current progress.

## Boundary
finalize-post requires prior durable fetch reservation, no prior cache/row,
one exact allowed post, fresh image event and finished row, no exploration.
Writer reconstructs and validates body-cache, image-event, save-row transitions,
including each intermediate preservation check and fixed row/image validator.
Only final complete state is committed; intermediate states are not published.
The constructed final state must exactly equal submitted after (no side writes).
No-leads additionally requires available body and complete zero-exploration row.
Source failure uses same existing support guard against the cache being atomically
published, with zero exploration and technical_failure row.
Image viewing remains an actual orchestrator action; tests' fixture receipts are
not real evidence and must never be used in production.

## Compatibility / recovery
Only use for posts with durable reservation and locally result-staged body.
If body-cache already accepted, use old separate image-event/save-row flow.
Do not delete journals or reset context to make finalize fit.
On uncertain CAS, readback; no automatic replay. Existing holds remain holds.
Expected CAS count reduces from 4 to 2 per new post. No measured production
speed claim, and repeated local validator/serialization checks remain.

## Compressed integration
This directory is rebased on /tmp/koyo-current-batch-compressed-candidate.
Compressed transport/packer/activation builder retained. Only route operation
allowlist gains finalize-post. Packer remains a mandatory activation pin.
Deployment copies network_runtime.py, connector_bridge.py, connector_transport.js
only and refreshes pins in existing activation; all existing progress and journal
files remain in place. No copied test fixtures or old activation may replace live
state. Runtime transport roots remain the pre-reviewed live/candidate allowlist.
