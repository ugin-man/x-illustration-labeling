# prod-0117 progress

- Worker: terra-prod-05; fixed run production-v4-001.
- Checkpoint accepted seven posts at queue commit 909146b61eca606e2eac5978f7c04b22f310fb03.
- The next post was saved locally after that checkpoint and remains unaccepted until a later checkpoint.
- Image view events are recorded in view-events.jsonl; view times are marked unknown when recorded after the call. An output-truncated image response was repeated only after no refusal and no visible pixels were confirmed.
- Individual post text retrieval failures are recorded as technical failures. A text search exposed popularity metrics; no values were retained in this report.
- Second checkpoint accepted 17 posts in total at queue commit 5187dce3a868369b0436b484fbd762fe1040b6b1. Text-search exposures to popularity indicators are recorded without values in the affected review flags.
- OPS_R2_STOPPED: checkpoint accepted 21 posts at queue commit ece93e6ba4f4623176f21d81f8bb10465ae82e66; local result count 21, uncheckpointed 0. No known preservation-pending issue. Worker stopped for ops-r2 transition without release or hold.
- OPS_R2_RUNNING: isolation audit found zero excluded-image matches; existing 21 accepted posts restored. First ops-r2 checkpoint added one accepted post, remote head ca027baa7bcb8e66d66146ab7c97efe8f9546317. A transient Git error during context processing recovered through the same CLI operation without repeating a confirmed source request.
- Paused after repeated Git communication errors on three consecutive posts. The first two recovered via the same ops-r2 context operation; the third remains unfinished. A preservation checkpoint accepted two additional locally saved posts, queue head 5426d249957f4da4e723dbcb800729cfc68d6b91. Current post 2095593157329367048 retains its draft and view records; context fetch returned a Git error and should be recovered via ops-r2 sidecar/marker rules before any source request. No image refusal occurred.
- Resumed after the recurring Git errors: ops-r2 claim restored 24 accepted posts, the interrupted context operation completed through the CLI with preserved history, and checkpoint accepted one further post at b5d76bdbdff387419ad93c797151eb0408171efc. Isolation audit found zero excluded-image matches before new image viewing.
