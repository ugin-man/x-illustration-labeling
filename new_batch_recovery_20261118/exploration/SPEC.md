# Exploration recovery v3, isolated candidate

## Authority and source evidence

This is a NEW reconstruction, not a claim to have recovered missing v7/v8 source.
The pinned formal manual R13 says: one focal-post body attempt, at most two additional query TERMS and three additional pages, and start new exploration within 60 seconds. One tool call containing two query terms consumes two slots. End early when evidence is sufficient; do not search merely to exhaust the budget.

The former worker directly confirmed the actual later runtime order:
1. `search-active` reserves the query.
2. Publish the reservation through the GitHub connector and verify acceptance.
3. Repeat `search-active` to receive ACKed permission.
4. Only NOW execute/await the web search tool.
5. Seal, and use the recorded summary value unchanged.

Therefore ACK marks the END of reservation-saving wait, BEFORE the external search. It is NOT an acknowledgement of a search result. Web tool execution/response waiting counts as exploration time. Earlier trial `active-v2-review` code that placed ACK after search was wrong and must not be activated.

All four preserved v2 single-search examples are reproduced numerically by the candidate without altering the source state: 5.505273103713989, 5.591034173965454, 4.348953008651733, and 12.402679920196533 seconds. No historical multi-search example exists; cumulative behavior below is an explicitly reconstructed extension of the same accounting principle, not historical-code equivalence.

## Exact accounting

Clock origin is the first reservation time. At instant T:

`active_seconds = T - origin - length(union(all reservation→ACK intervals, all verified management-read intervals))`

- Pending reservation→ACK wait is excluded, but no tool permission is available while it is pending.
- Time after ACK, including tool execution, response waits and reasoning before the next operation, is included.
- Only actual `fetch` and `ls-remote` measured by the trusted Git wrapper are deductible control waits. Search/page requests must NEVER be included among them.
- Interval union prevents duplicate/overlapping deductions.
- A tool started below 60 active seconds may finish after 60. Record the real longer elapsed time; do not clamp it to 60. No NEW tool request may start at or beyond 60 active seconds.
- Reserve checks the budget and consumes each query term/page before invocation. A second permission check at actual dispatch rejects a stale permission if the worker waited until its active budget expired after ACK.
- Reservation IDs, ACKs, results and seals are immutable. A failed external attempt still consumes its reserved count. No automatic refund/reset/replay.

Example: reserve at 0, ACK at 100, search from 100 to 110, reason until 115, page reserve at 115, ACK at 200, page from 200 to 210, seal at 212. Active elapsed is 27, not 12 and not 212.

## State and trusted interfaces

`transition(before,event,authority)` is the only clock-state builder. `validate_transition` replays an event and requires exact candidate equality at the writer boundary. Query count/history, order and timing cannot be supplied as independent claims.

Binding includes plan hash, post, worker and lease token. ACK receipts also bind reservation-clock digest and accepted head. The connector wrapper may issue an ACK ONLY after explicit successful update_ref ACK and exact remote readback. Lost/denied/cancelled ACK never grants a new external request even if later readback finds the reservation.

`Authority` is a trusted, process-local receipt issuer, not an untrusted object loaded from a source file. Receipts include SHA plus a process-secret MAC and must exactly match its issuance registry. Recomputing a SHA on invented timestamps is insufficient. `TrustedGitRecorder` obtains wall/monotonic timestamps itself around the fixed authorized Git runner; users/callers cannot pass measured times through that wrapper. Lower-level issuer methods exist for wrapper use and deterministic tests, not as public APIs for the model/source JSON.

`run_external_once` consumes the one-use capability, durably journals intent, THEN calls the tool runner. Failed journaling causes zero tool calls and consumes the capability conservatively. Tool failure is recorded and never automatically retried. If the process dies, the process-local authority is lost; an old persisted ACK does not recreate permission. Recovery must preserve an ambiguous pending post and continue independent work, not reset its clock.

## Preservation

Existing `budget`, `reservations` or `exploration_clock` records cannot be silently replaced/reset by this implementation. Old accepted rows and old sealed clock records stay unchanged. New-clock schema belongs under an explicitly activated new runtime revision. Posts with no genuine search leads do not need a new clock, and remain independent of this reconstruction. Body-attempt accounting stays separate and one-time.

## Required integration before live use

1. Independently review this spec and implementation, including cumulative behavior.
2. Pin this module in activation and add pure replay validation to the live writer. For legacy clocks, either preserve unchanged or use a separately reviewed explicit migration; never infer/reset timing.
3. Connect ACK issuance to the existing verified connector response/readback, with accepted full dispatch-state hash AND the extracted clock digest checked. An arbitrary `acknowledged=True` supplied by source data is not evidence.
4. Connect `TrustedGitRecorder` to the fixed q.git callable and bind the actual observed head, request and lease. Persist provenance of measurements. This test authority is process-local; integrate durable signed measurement/journal recovery or fail closed on lost unaccepted state.
5. Connect single-use dispatch to the real web tool bridge. The current Python module never makes external calls itself; its test runners are fixtures. Do not call the web tool outside this gate.
6. The live writer must freeze the clock's research time at seal preparation, while excluding later seal-save overhead. Do not rewrite seal timestamps after publication.
7. Run an isolated end-to-end connector/tool/journal simulation with at least two searches and three pages, plus crash and lost-ACK injection, before enabling real exploration. Current unit tests are strong state-machine coverage, not remote end-to-end approval.

No remote writes, body requests or web searches were performed for this candidate.
