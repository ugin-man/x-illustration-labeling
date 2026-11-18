# Exploration recovery v3: persistent bridge candidate (isolated)

This is a **new explicit revision**, not restored v7/v8 source. R13/R5 research caps stay 2 query terms, 3 page requests, and no request starting at/after 60 active seconds. Prior `SPEC.md` defines clock semantics. Actual external tool waits remain counted. No live state, searches, body requests or connector writes were made to develop/test this candidate.

## Minimal persistent runner

One SQLite file per fixed post/context contains one JSON record: clock, unapplied writer events, authority key + issued receipts + consumed IDs, blocked marker, exact remote state digest/head, and per-request durable intents. It is explicitly created with mode 0600 and never auto-created during resume. It contains internal authentication material and must **not** be uploaded as public code or exposed in logs. SQLite FULL synchronous transactions atomically persist clock progression, consumed authority, and dispatch intent. BEGIN IMMEDIATE serializes clients. Tests reopen the same database after each phase; authority is restored, not regenerated per CLI. Missing/corrupt authority refuses continuation. No deletion/reinitialization recovery is provided. Environment loss must preserve the ambiguous reservation and stop, not reconstruct permission from remote acceptance.

### Reservation / connector bridge

1. Read current full state and check fixed plan/post/token + lease margin.
2. Purely replay accumulated clock events plus new reservation against remote clock; candidate must differ only at fixed clock path. Persist blocked reservation **before** connector invocation.
3. The `publish` installation callback must invoke the existing reviewed connector CAS path (create tree/commit, verified single parent/tree, immediately revalidate envelope/lease, expected_sha update_ref with force=false, complete readback). No generic or direct Git push alternative.
4. `connector_result` adapts current `execution_receipt` plus full envelope/readback. It checks exact envelope/content hashes, post, operation, candidate/head and state. Runner then requires explicit ACK=true, accepted=true, request_permitted=true, exact full state equality, full-state digest and exact clock readback. Only then issue persistent ACK proof. Lost/failed ACK leaves blocked=true even if accepted remotely.
5. ACK records trusted wall time after readback. Reservation→ACK saving interval excluded. Actual search starts later.

### Dispatch

Fresh snapshot immediately precedes dispatch. Fixed installation guard requires current leased prod-0002, exact plan/hash/token/Koyo owner, allowlisted uncompleted post, and >30s lease margin. Remote head **and whole state** must still equal ACK readback. Actual sampled wall time then passes the clock's 60s gate. One transaction stores external_started + consumed permission + durable started intent. Only successful COMMIT may invoke actual tool adapter. Any tool/response failure leaves started intent, preventing retries across restart. Finishing stores result digest and actual finish time; web tool duration counts.

### Management clock

`measured_git_read` wraps a fixed q.git callable. It samples wall+monotonic clocks itself, permits fetch/ls-remote only, persists bound proof before returning result. Failed reads still record measured waiting when possible. Clock rejects inconsistent durations, overlap with external calls, rollback and forged proofs. Union deduction avoids double subtraction. Fresh dispatch snapshot time is conservatively counted unless production snapshot itself is instrumented through this recorder. It must not be subtracted using caller-supplied elapsed numbers.

### Writer and row

`validate_full_write` reproduces the entire pending event sequence, requires exact resulting clock, and forbids any other field change. This protects other contexts, historic clocks, rows and Terra state. `seal` fixes numbers before saving; `flush_seal` cannot alter them. `validate_sealed_row` checks the new row receipt against full clock digest + exact seal + post. It is an additional check, **not a replacement for existing fixed classification validator or R14 evidence checks**.

## Remaining live wiring gates (not hidden)

- Current production runtime still rejects these new exploration operations/clock field. Candidate intentionally does not modify it or activation.
- Mount clock only at a fresh context with no legacy budget/reservations/clock. Production initializer must call `new_clock(binding, legacy_context)` before `Store.initialize`; do not reset old contexts.
- Install `Runner` with the actual reviewed connector `publish` capability and route its `execution_receipt` through `connector_result`. The current CLI receipt alone lacks full state; retrieve through `readback` inside trusted bridge and extract exact clock digest.
- Pin this module, exploration module, updated writer, transport and guard implementation in reviewed activation. Require `validate_full_write` in the publish boundary, not just optional call-site validation. Same persistent Authority must be accessible for replay.
- Actual web tool dispatch spans the functions/CLI boundary. Implement exactly one trusted host runner around durable intent; do not expose a replayable JSON permission to arbitrary callers. This candidate injected synchronous test tool is not the installed real web executor.
- Instrument actual snapshot Git reads with trusted recorder without recursive Store transaction; current candidate counts those waits conservatively. Existing managed-read proof version remains immutable.
- Add row `exploration_receipt` to fixed validator through reviewed schema migration or approved equivalent existing fields. Current production row schema may reject it. Do not drop this check for compatibility.
- Backup design must retain runner authority securely without uploading credentials to repository. If secure persistence unavailable, fail closed after environment loss.

## Tests

`python -m unittest -v`: 37 total (23 clock + 14 bridge) pass. New end-to-end mock transport performs 2 searches + 3 page opens, all real-clock calls simulated, then seals/writes/readbacks; 500 seconds metadata delay excluded, 15 active seconds retained. Also lost ACK despite remote acceptance, database-journal failure, tool-result loss, restart after ACK and after invocation, missing/corrupted authority, changed head/lease, 60-second gate, whole-state wrong readback, managed waiting, sealed-row linkage and old-clock/Terra write rejection. These are isolated bridge tests, not production connector/tool execution proof.

## Added real-protocol isolated bridge

`protocol_bridge.py` now calls a copied, unchanged production `connector_protocol.py` for envelope construction, fresh validation, pre-update-ref checks, readback and execution receipt. `ClockWriter` forces pure clock replay on both authorize_transition and preservation, plus fresh fixed scope guard. `ProtocolPublisher` uses installed connector method capabilities, demands verified tree/commit metadata and expected-SHA CAS, and keeps lost ACK non-permissive. Actual connector methods remain **mocked** in tests; no MCP calls or live state writes occurred.

Four added tests bring total to **41 passed**. The same actual protocol functions now perform 2 search + 3 page reservation/ACK/dispatch operations and seal/readback with fake Git/connector, plus lost ACK accepted remotely, token change, and forbidden post. This is stronger than a fake publisher alone, but not a live-operation proof. Production activation currently forbids exploration and must remain so until this dedicated ClockWriter guard is independently reviewed/pinned and host tool wiring is installed. The copied runtime snapshot is read-only dependency evidence; do not copy it over concurrently developed production files.

## Audit correction: dedicated guard and original preservation retained

`ClockWriter` now requires `ReviewedClockGuard` (not a generic callable). This guard only accepts explicit **isolated-exploration-review-v3** activation, validates all integration and copied-runtime code pins, exact plan payload SHA and claimed SHA, original catalog/manual/contract/config hashes and manifest membership through PinnedInputs, the fixed 50-post prod-0002 plan, permitted positions 19–50, held position 17, baseline accepted rows/identity and held contexts/events/rows. It also requires a recorded single body attempt and valid available focal-post cache. Missing body/cache or legacy budget/reservations fails closed.

Original IndexWriter.preservation is invoked on before/after with **only the selected new-schema clock removed from both projections**. Pure replay validates that clock independently. Therefore existing body history, immutable rows, events, operations, namespaces, destination/owner/lease, input pins and row validation are not silently dropped. Original authorize_transition cannot accept the new clock schema and live scope; dedicated guard supplies only the reviewed isolated clock authorization. Existing production activation still cannot enable this path.

`initialize_fresh_store` requires the same dedicated guard and refuses any existing clock/budget/reservation via new_clock. Initial reservation may add the new clock only through replay from the exact fresh empty clock. Store.initialize also refuses nonfresh clock imports. Existing Authority must be reopened, never recreated from remote history.

Regression coverage now includes missing cache, missing body reservation, tampered plan under unchanged claimed SHA, wrong activation pin, held-post mutation, denied reinitialization, and first reservation from an absent fresh clock. Real catalog/input validation is exercised on a local copied remote-state fixture, with fake connector/web adapters only.
