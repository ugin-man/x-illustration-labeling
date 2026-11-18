# Synthetic network integration only
Only these same-repository test branches were written:
- codex/koyo-checkpoint-network-archive-20261118
- codex/koyo-checkpoint-network-aggregate-20261118

Both start from code-only snapshot a3e781d8a81fbebdb63a3c6a69987af024b2c948. Test data are artificial rows and identifiers, not research posts, bodies or views. Production dispatch/main were not read or written by this test harness. No credentials were materialized.

The separate connector test harness uses exact branch/path scopes; later hardened with source/input SHA256 activation pins verified before every connector call. Existing production ReviewGate continues to reject live adapters. This is not an activation of the production runtime.

Two completed synthetic stages were committed separately to the remote archive, then a fresh function invocation fetched stage/state solely from remote and prepared/validated the aggregate in a new Python process. Two rows were accepted and read back exactly. No local stage file was used for reconstruction. This demonstrates stateless runner recovery, not a physically destroyed/reprovisioned cloud environment.

A competing commit was made on the synthetic aggregate branch, then an old-head update was attempted. GitHub returned UNKNOWN, and readback proved the competing head remained intact. Because the error was not a typed CAS mismatch, it is not conclusive proof of all connector CAS semantics. No retry occurred.

For simulated ACK loss, the successful update response was deliberately not used as completion evidence. Fresh head/content readback verified acceptance, with zero repeated writes. This is client-side fault injection, not an observed real lost response.

After pin hardening, the production branch name was rejected before any I/O and a current test-branch read succeeded. No test of actual security rejection was manufactured or bypassed.

The generic Python aggregate adapter was tested locally with actual research validators earlier; this separate network test uses the explicitly synthetic validator. Joining production validators/scope and network transport remains unimplemented and must receive independent review before any production application. Network event timings are protocol tests, not comparable baseline/optimized speed measurements.
