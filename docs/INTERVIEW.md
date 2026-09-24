# Interview defense

## Two-minute explanation

EventPulse demonstrates that streaming correctness is more than low latency. Kinesis delivery is
at least once, so the application owns immutable event identity, idempotent effects, event-time
watermarks, checkpoint atomicity, and replay. The local kernel makes those invariants executable;
the Terraform module defines a bounded AWS lab; the claims file prevents design from being
presented as measured production execution.

## Questions to expect

1. **Why not claim exactly once?** Transport can redeliver. The defensible claim is idempotent
   application effects backed by identity and checkpoint evidence.
2. **What happens to late data?** It remains auditable but does not silently mutate the current
   online view; a controlled reprocessing version is published.
3. **What breaks under a celebrity key?** Per-key ordering creates a hot partition. Measure skew,
   then use two-stage aggregation or salt only commutative aggregates.
4. **How do you recover after a crash?** Restore the last committed checkpoint and replay; the
   state digest must converge.
5. **What has actually run?** Only claims marked `LOCAL_VERIFIED` until an AWS evidence bundle is
   committed.

