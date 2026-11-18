# Review candidate: dedicated exploration host v3

This directory is a separate, disabled-by-default candidate. It is not the missing v8. It does not overwrite the working compressed/generalized classification runtime. No live connector, search, body fetch or remote write was executed while building it.

## Connected path

`exploration_host.js` is a functions-runtime host taking the existing `tools` object. It uses the actual GitHub connector method names and argument shapes, and actual chat_search search/open shapes. The pinned JS imports no live credentials and invokes nothing on load. A fixed config path and CLI path are enforced.

1. `host_cli.py reserve` -> dedicated guard + body/cache/provenance/manifest/activation + SQLite reservation and pending envelope.
2. ASCII envelope is zlib/base64 chunked; JS uses the independently reviewed bounded fflate/SHA decoder copied from the compressed classification candidate. Original full `state_json_content` remains an untouched string, avoiding JSON numeric canonicalization drift.
3. JS create_tree -> create_commit -> fetch exact commit -> CLI `pre-ref` (fresh replay/scope/head/lease) -> connector `update_ref(expected_sha, force:false)` -> CLI full readback and exact clock digest -> durable explicit ACK proof.
4. CLI `claim` does fresh full snapshot + head/token/post/lease/60-second gate and commits consumed permission + external_started intent before returning arguments. Its return cannot be obtained twice, even on process restart. Pinned JS invokes exactly one actual web tool call. If host/response is lost, do not rerun the tool; the intent remains consumed.
5. JS records actual result through CLI `finish`. Larger results are ASCII-chunked (up to 4 MiB) into the same private store. Chunk ordering and intent binding are checked. Local result-transfer and host reasoning time count toward active time; actual Git fetch/ls-remote waits are measured by the trusted `clock_read` wrapper and deducted with the clock union rule.
6. `seal` fixes counters before saving. `saveRow` routes through `SealedRowWriter`: the exact saved context seal determines existing fixed-row `searches/pages/elapsed_seconds`; original fixed schema and image/provenance validator run unchanged. No new row field is invented. The writer rejects any other mutation. Original preservation still protects all prior rows/body history/events/operations/Terra.

## Dedicated activation and setup (not performed)

`prepare_live_activation.build` produces a document/config in memory from a freshly verified complete baseline, exact head, fixed binding and independent review reference. It pins the original source inputs, all integration/runtime code, host and CLI; exact prod-0002 allowed positions 19–50; held17; baseline accepted rows. It fixes 2 queries / 3 pages / 60 active seconds and `authority_loss_policy=stop-no-reinitialize`. The accepted activation mode is explicitly `reviewed-live-exploration-v3`, not the existing no-exploration classification activation.

After independent review, an authorized coordinator may write its returned activation/config/baseline under this candidate directory and call host.initialize ONCE for a fresh body-cached context. Do not create an activation merely because tests pass. Initialization uses the same dedicated guard and rejects all preexisting exploration clocks/budgets/reservations. Existing local Authority must always be reopened. There is no recovery-from-remote-permission feature.

The actual use in functions runtime is to load this pinned JS, instantiate `makeExplorationHost(tools, '/tmp/koyo-exploration-host-candidate/host_cli.py', '/tmp/koyo-exploration-host-candidate/live-config.json')`, then await request/seal/saveRow. No call should run concurrently with another Koyo writer for the same token; fresh expected-head CAS and full-state checks fail closed if it does. Lease renewal remains the original reviewed classification coordinator's operation, not an expansion in this host.

## Security and failure rules

Authority key, receipt registry, consumed intents and pending envelopes live in a 0600 SQLite database with synchronous FULL transactions. Never upload this database/key to the repository or logs. Backup only source/tests/runbook. If the environment/store is lost, stop: remote reservation evidence prevents initialization/reissue. A missing store, corrupted receipt, ambiguous ACK, consumed intent, changed scope/token/head or failed journal is not permission to retry a search. A result transfer crash also leaves the request consumed; no web retry. Only complete successfully returned tool calls can be finalized/sealed.

## Verification

- Inherited 48 tests remain the baseline.
- Python host tests exercise the real split HostBridge, live guard, private persistent Authority, actual protocol functions, 2 search + 3 page calls, seal, fixed-schema row save/readback, lost ACK, consumed claim restart, altered elapsed and missing image evidence.
- `node test_exploration_host.js` checks real MCP argument/response shapes, explicit success, page-open routing, lost connector ACK and lost tool response.
- `node test_joined_host.js` joins the REAL pinned JS host to subprocess CLI bridge, SQLite, real protocol and a file-backed mock remote. It completes 2 queries + 3 pages + seal with all external connectors/tools mocked. It intentionally sends the exact raw state JSON string to the mock remote, as GitHub create_tree does.
- Tests labeled FIXTURE contain synthetic classification/evidence solely to exercise validators. They must never be copied as actual post decisions or image-view evidence.

No known code-level connector/web/seal-row adapter remains as a placeholder. Production activation issuance, installation, and one independently authorized actual execution are still pending review. Test success is not evidence of live tool success.

## Host-boundary audit correction

Claim responses now carry budget remaining and lease remaining, bound into the committed consumed intent. The pinned JS samples its own clock BEFORE awaiting claim, then conservatively subtracts the entire claim roundtrip immediately before invoking the web tool. It requires >1s research margin and >30s lease margin; backwards/nonfinite host time refuses. This does not depend on Python/JS wall clocks being synchronized. Expired claims stay consumed and cannot be reissued. The 1s is dispatch safety headroom, not an increase in the formal 60s cap.

A returned `isError:true` response is a completed *attempt*, not successful research. It is durably recorded with result_state=technical_failure; the JS then throws and does not automatically continue/retry. Fixed-row saving cannot convert required failed exploration into unknown/no-evidence completion. R14 allows already sufficient source-backed observed or not_applicable context attributes to remain intact; otherwise the affected context must retain technical_failure/tool_unavailable. Exceptions/lost responses leave an unfinished consumed intent and cannot seal.

Management wait exception: successful snapshot fetch/ls-remote waits are measured and excluded. If snapshot itself raises, its transaction rolls back, including wait evidence. A later attempt therefore conservatively counts that unsuccessful wait rather than deducting an unpersisted receipt. This may stop exploration early, never enlarge its budget. We do not claim bit-for-bit historical v8 timing equivalence or that every failed management wait is excluded.
