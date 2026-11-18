# Current prod-0002 continuation candidate

DO NOT deploy until independently reviewed. Only changed candidate files should replace their live counterparts; do not copy old activation, journals, raw state or receipts. Source snapshot is live-final-state.json @376c1ca5bc3d2edbe7573896e264ca5fb5233a63, 67 total Koyo rows, 17 in prod-0002. Underlying pinned repo remains /tmp/x-recovery-isolated @e07181e8.

Scope is exact frozen plan indices 18..49 (32 remaining posts), excluding uncertain index16/post2096015385070039138. The accepted first16 + index17 remain an immutable17-row baseline. No next-batch claim, no external exploration, no Terra change. The user’s standing permission covers continuing, but the current reviewed implementation deliberately does not infer the missing exploration-clock semantics.

After deployment and fresh head/state verification:
`PYTHONPATH=/tmp/x-recovery-isolated:. python prepare_current_batch_activation.py VERIFIED_BASELINE_JSON VERIFIED_HEAD REVIEW_REFERENCE`
This is LOCAL ONLY. It requires exactly the original17 accepted baseline; once more posts are accepted, retain this original activation/baseline rather than rebuilding from a later snapshot. On recovery reconstruct original baseline from its known repository commit and recheck all later accepted rows.

CLI, run from restored /tmp/koyo-replacement-prototype:
- `python connector_bridge.py status`: read-only current eligible list.
- `python connector_bridge.py prepare renew`: current Koyo lease extension, connector outbox only.
- `python connector_bridge.py prepare reacquire`: expired OWN Koyo lease only, requires current-fencing-receipt.json with all_previous_koyo_writers_stopped=true, verification_reference, expected_head and expected_lease_token matching current remote state. Never infer fencing from age alone.
- `python connector_bridge.py prepare body-reserve POST_ID`
- Execute the audited connector_transport.js with `connectorFolder` set to the returned folder. It handles validation, SHA transport, create_tree/commit, expected-head CAS and readback. No CLI push. On denial stop; on uncertain ACK never issue the body request.
- `python connector_bridge.py fetch-body POST_ID`: accepted same-post envelope/ACK/current-head/hash/lease/journal checks, then ONE pinned body call. Journal is per-post and written before dispatch.
- `python connector_bridge.py prepare body-cache POST_ID`, then publish returned outbox. Readback marks its stage accepted. Never delete or reuse a stage journal to refetch.
- Actually view EVERY pinned attachment; save list to post-runtime/POST_ID/view-receipts.json, each carrying exact post_id, media_index, sha256, actual at timestamp, tool and honest tool_call_id. Hash checking is not viewing. `prepare image-event POST_ID` appends all per-post receipts once and rejects cross-post/image receipt or duplicate evidence.
- Write fully validated result to post-runtime/POST_ID/row-final.json. `prepare save-row POST_ID`, publish and readback. Genuine no_leads (zero extra search), or durable source failure with source_unavailable, are allowed. Never falsify no_leads to avoid search.
- If external exploration is genuinely needed: `python connector_bridge.py hold POST_ID external_exploration_required`. This is LOCAL operational bookkeeping, not a research exclusion or accepted label. Continue another safe pinned post. Held17 is always hard-blocked regardless of local hold file.

Every outbox is unique: connector-outbox/POST_ID/OP-UUID, lease outboxes use lease/OP-UUID. Latest per-post operation pointers are maintained under post-runtime/POST_ID/outboxes. No old one-post bridge files/receipts are treated as permits for a new post. Unknown outcome => reconcile exact existing candidate and state, never redo body fetch. Activation pins all7 runtime modules. Live IndexWriter.publish always refuses CLI push; the original connector path is the only supported live write route.

Research snapshots/rows/images are not included in code backup. This candidate does not implement next50 selection or legacy clock reconstruction.
