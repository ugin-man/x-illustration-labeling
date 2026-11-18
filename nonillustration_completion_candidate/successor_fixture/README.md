# Synthetic successor activation simulator

This is **not** a deployment or real approval mechanism. `issue_successor` always refuses because no authenticated real-issuance approval adapter is available. Passing `approved=True`, user text, or a synthetic test grant does not enable issuance.

`simulate_successor` uses generated synthetic IDs, catalog, state, lease and placeholder events in a disposable `/tmp/synthetic-successor-*` fixture. It returns an explicitly non-deployable wrapper in memory only. The harness copies existing code as read-only dependencies, loads the unmodified `new_batch_scope` validators from isolated old/new bundles, uses `PinnedInputs` and the original fixed row validator, and tests both old and successor candidates. No real state, body, images, activation, journals or authority databases are read. Actual-view fixture events are labelled synthetic and never used as live evidence.

Only the approved runtime module differs in bytes; all other activation semantics and original synthetic genesis remain identical. Old/new path translation occurs only between two synthetic bundle directories. This is not production re-pinning. No live paths are written. No network or connector functions are present in this simulator.

Run `python test_successor_fixture.py`. The code-only dependencies are currently in the authorized workspace at the paths listed in the test header; they are not operational snapshot dependencies.

20 tests pass: original document/state preservation, unchanged real validators, mandatory mock approval+review, real issuance denied, lease/state/head drift, pending work/concurrent writer, extra/missing/tampered module, fixed-contract change, scope/genesis mutation, rollback, symlink/production root, no writes/network/process during simulation. These tests do not establish a trusted approval source. A future real issuance adapter, deployment transaction and independent review are still required and are intentionally absent.

The mock authority is clearly marked and is not a security primitive. Production refusal is unconditional. Do not remove the refusal, unwrap synthetic candidates into live configuration, edit the current pins to match, or treat this artifact as issuance permission.
