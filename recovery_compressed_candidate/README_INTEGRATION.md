# Optional compressed transport integrated with current-batch runtime

Isolated review candidate only. No live files, activation or remote refs changed.
Source: /tmp/koyo-current-batch-candidate; exact source hashes in SOURCE_HASHES.json.

Changes:
- connector_transport.js bundles pinned fflate 0.8.2 MIT and strict codec, replacing only raw pack transfer/decode. Generalized per-post/UUID/lease route regex and cross-post guards are unchanged. Runtime packer path is derived from the matched approved route root, not hardcoded.
- connector_bridge.py requires pack_compressed.py AND connector_transport.js in activation pins before any operation. prepare_current_batch_activation.py includes both in its code hash map.
- protocol, network runtime and research/state transition code are unchanged.
- Inspect transport-orchestration.diff and two Python .diff files for small semantic changes. Full bundle is intentionally larger due to pinned vendor.

Checks passed:
- Codec 12 tests (full old/new envelope byte equality, corrupted/truncated/bad checksum/base64/nonASCII, raw bounds and decompression bomb).
- JS transport: success, split output, denied ACK, lost ACK, cross-post refusal (5 cases). CAS expected_sha/force=false and pre-ref order asserted; uncertain ACK disables body; cross-post mismatch calls no connector.
- Five invalid generalized routes rejected before any tool call.
- Python current-batch scope 10, connector protocol 1, body gate 5 tests (16 total). Includes exact32 scope, held17/accepted18 refusal, Terra/old rows preservation, no exploration, no CLI push; missing/changed packer and bundle pins refuse before body call.
- Network runtime22 tests pass. Results recorded alongside code.

Fixture import errors on first test run were corrected by adding the new mandatory packer to temporary fixture code pins and copying the existing row fixture. No runtime guard relaxed.

Observed real envelope:3137565 original ASCII bytes / SHA b83417ee732b721ae066ac6077da5a44d330e4861b13766247c3a888df230b0e; zlib181751 bytes; base64242336 chars;131 chunks to11,92.28% payload reduction. Not an end-to-end speed measurement.

Dependency: official https://registry.npmjs.org/fflate/-/fflate-0.8.2.tgz, MIT, scripts disabled. Vendor UMD SHA c3b34f2e9f5e74d4d7d64e01cac7a0c01954c6c406414d42185c7b53d6875ddf. Full license in vendor/fflate-LICENSE. Codec and packer are unchanged from isolated prior candidate.

Rollout after independent review:
1. Only between operations with no pending uncertain publication. Keep existing fresh state, holds, accepted rows and UUID journals; do not restore fixture state/activation.
2. Install reviewed bundle and packer, updated bridge, activation-builder source into live path. Existing production activation must be re-pinned to reviewed bundle/bridge/packer, preserving source/baseline/scope semantics. Builder currently requires original17-row baseline, unchanged; do not invoke it against a later state expecting it to accept a new baseline.
3. Loader should read full bundle with max_output_tokens>=40000 and verify complete hash, not a truncated string. Bundle is ~42KB.
4. Revalidate activation before any write. No automatic fallback. Any compression/length/hash error stops before connector writes. ACK uncertainty retains existing stop/no-body semantics.
5. First actual compressed publication still requires ordinary readback verification; current tests use mock connectors only.

This isolated directory is deliberately NOT an accepted route root: tests use approved generalized path strings with mocked tools; production path allowlist was not broadened. Preserve the exact regex when deploying.

Backup code/tests/license/diffs/hashes only. fixture-pack and live-*.json are local research test fixtures, not part of code backup. No credentials included.
