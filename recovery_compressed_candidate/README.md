# Compressed transport backup update

This directory is a separate, complete code snapshot of the reviewed compressed transport integration. The previous recovery_candidate directory is retained unchanged for history, not used as a fallback. Parent reports independent audit passed and the first live compressed body-cache publication was accepted and read back; this backup task did not perform that production operation. README_INTEGRATION.md preserves the earlier pre-rollout record; this paragraph supersedes its rollout-status statements only.

The exact reviewed bridge/transport/packer hashes are in MANIFEST.json and SHA256SUMS. SOURCE_HASHES.json records the pre-compression inputs, not the final runtime hashes. Activation must pin the added pack_compressed.py as well as all seven runtime modules. Preserve original baseline/scope and per-post journals. Never blindly run activation generation against later state.

Bundled fflate 0.8.2 retains its MIT license under vendor/. No fixtures, raw states, row data, activations, journals, body caches or images are included. Historical one-post author_live_row.py/live_one_prepare.py were deliberately excluded because they embed post-specific operational/label data and are not the current runtime.

# Koyo recovery: current prod-0002 continuation snapshot

This is a recoverable source snapshot, not the missing v8 implementation and not an automatic live launcher. It is deliberately separate from production dispatch/job branches. Original dependency: `e07181e8cd5926a67e588932224ab51b3ff085e1` (ops-r5).

## Snapshot identity and contents

`MANIFEST.json` records capture time and the SHA256/byte length of every snapshot source file. `SHA256SUMS` covers all files except itself. The preceding commit a106eb24e3d4fe9823493c3d351abbaeb7835cf1 preserves the one-post recovery that accepted target `2096139409821405202` at commit `376c1ca5bc3d2edbe7573896e264ca5fb5233a63`, bringing Koyo to 67 accepted records. This is historical context, NOT a claim about the current queue.

Included: seven runtime modules, their tests, independent saved-row validation helper, isolated rehearsal script, clock-evidence notes and the chronological restart checklist. No raw dispatch state, lease/activation records, tokens, images, bundle archives, body caches, generated classifications, credentials or environment configuration are included.

`RESTART_CHECKLIST.md` is a chronological engineering log; later sections supersede earlier incomplete-stage statements. This README describes the captured final state. This commit generalizes the reviewed scope to the frozen remaining 32 posts (plan indices 18..49) in prod-0002. The original 17 accepted rows remain the immutable baseline; uncertain index16/post2096015385070039138 remains held. These counts define the activation scope at the baseline, not the current remaining queue. External exploration and next-50 claiming are NOT connected. See CURRENT_BATCH_RESTART.md for per-post operation and recovery instructions. The parent reported independent review of the four changed runtime hashes in MANIFEST.json; the warning at the top of that original development document means any future altered version requires review, not that this snapshot is awaiting new user permission.

## Restore code, without starting classification

Use a fresh environment. Do not overwrite an existing checkout/runtime. Do not run saved activation files from an older machine.

1. Read the repository `AGENTS.md` and task-specific rules.
2. Clone this repository into a separate working directory and fetch the backup branch `codex/koyo-recovery-runtime-20261117`. Record the immutable commit obtained and verify `recovery_compressed_candidate/SHA256SUMS` with `sha256sum -c` from that directory.
3. Create the dependency checkout at exactly `/tmp/x-recovery-isolated`, detached at `e07181e8cd5926a67e588932224ab51b3ff085e1`. Example (only when the path does not exist):

   ```sh
   git clone --no-checkout https://github.com/ugin-man/x-illustration-labeling.git /tmp/x-recovery-isolated
   git -C /tmp/x-recovery-isolated checkout --detach e07181e8cd5926a67e588932224ab51b3ff085e1
   ```

4. Copy the verified files from `recovery_compressed_candidate/` into a new `/tmp/koyo-replacement-prototype/`. The current source deliberately retains these hardcoded paths. Copying code into place does not authorize or start production work.
5. Set `PYTHONPATH=/tmp/x-recovery-isolated:/tmp/koyo-replacement-prototype` for Python commands. Standard Python, Git and Node are enough; do not install unrecognized software.

## Rebuild test fixtures read-only

The fixture data were intentionally excluded from the backup. Tests use historical queue snapshots and are NOT based on arbitrary current state.

- Fetch historical commit `ec4c8344d92c8ae390a81186218180a36ff9bfbb` read-only into the dependency checkout. Its `state.json` must be saved locally as `/tmp/x-state-recovery.json`; this contains the original 50+16 baseline used by tests.
- Fetch historical commit `376c1ca5bc3d2edbe7573896e264ca5fb5233a63` read-only. Extract only `koyo_index_handoffs` → the handoff whose `job_id` is `prod-0002` → `rows` → `2096139409821405202` into local `live-row-final.json` alongside the tests. This is a historical fixture, never a row to re-submit.
- Also save the full historical state.json from 376c1ca5bc3d2edbe7573896e264ca5fb5233a63 locally as live-final-state.json beside the tests. New current-batch scope/body-gate tests require this exact 67-total/17-current baseline, not a later production state.
- Never upload those reconstructed local states or tokens as part of code backup.
- Run `python -m unittest discover -p 'test*.py' -v` from the restored candidate directory. These tests use local temporary Git remotes; the `IndexWriter` live path remains disabled unless explicitly configured by reviewed activation. Run `node test_compressed_transport.js` and `node test_route_refusal.js` for transport and invalid-route tests. The standalone `test_codec.js` additionally requires the excluded local fixture-pack; reconstruct genuine envelope fixtures read-only before using it, never fabricate live receipts.
- Run the dependency regression separately with `python -m unittest discover -s tests -v` in `/tmp/x-recovery-isolated`.

The connected `run_rehearsal.py` additionally needs a verified real-image bundle and an actual fresh image-view tool receipt. Do not fabricate that receipt. Its fixture deliberately removes one already accepted row in an ISOLATED LOCAL remote and then replays it; that is not new production work.

## Production restart invariants

- The original operational save route is the authenticated GitHub CONNECTOR, not Git CLI push. Public CLI reads can succeed while CLI writes return HTTP401. Do not retry or switch credentials to bypass an authentication/safety refusal.
- `connector_protocol.py` validates state transitions, rebuilds and compares the envelope, verifies content bytes/hash, tree and exactly one expected parent, and requires remaining lease margin.
- `connector_transport.js` checks ASCII chunk SHA, fresh validation, tree/commit content, runs pre-ref validation immediately before `update_ref(expected_sha, force:false)`, then reads back. Failed/denied/lost ACK never grants permission for a new body request, even if the ref later appears accepted.
- Every connector/bridge/transport file must be included in a newly reviewed activation. Never copy historical activation/lease tokens into a new run. Activation must pin current code hashes and retain the original 17-row baseline from 376c1ca5bc3d2edbe7573896e264ca5fb5233a63. Do not regenerate a broader baseline from later accepted rows. Reconcile the latest remote state independently.
- Verify the latest head, accepted rows, all Terra data, all existing body reservations and the old Koyo process/lease state. Expired Terra leases are not permission to steal work. Reacquisition is only for the own Koyo handoff after verified old-writer stop/fencing.
- Body fetch is exactly once after acknowledged durable reservation and dispatch journal. Preserve failure/ambiguity. Post `2096015385070039138` was held because its previous request history could not be proven; do not re-fetch it based on missing cache alone.
- Actual per-post image viewing and pinned-byte verification are both required. Hash/decode/OCR alone is not viewing.
- This version is restricted to the exact remaining 32 frozen-plan posts in prod-0002, at most 32 new rows beyond the original 17-row baseline, and no external exploration. Each transition changes at most one post. Held17 and all previously accepted rows remain protected. It permits genuine `no_leads`, or recorded source failure only when the durable cache proves failure/unavailability and the row records `technical_failure/source_unavailable` with zero exploration. It is not a general autonomous worker.
- Necessary text retrieval failure is recorded according to the fixed manual; it is not relabeled as original work or no-leads. Keep image-observable answers separate from text-dependent failures.
- Preserve existing sealed exploration clocks. The later wait-exclusion implementation is evidenced by saved v2 receipts, but multiple-search semantics were not fully recovered; see `CLOCK_EVIDENCE.md`. Do not silently revert or infer new production research rules.
- Confirm acceptance and preservation by full readback, not only tool success.

## Do not resume blindly

Detailed commands are in CURRENT_BATCH_RESTART.md, but never run them blindly. First reconstruct and verify the above inputs, reconcile the current queue, and have the controlling worker select the approved, reviewed scope. Existing user authorization permits ordinary approved work; these checks prevent duplicate source requests and corruption, rather than asking for unnecessary new user permission.
