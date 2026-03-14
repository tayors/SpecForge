# Modeling Patterns

Use raw TLA+ modules for stateful behavior:

- retries and idempotency
- queues and leases
- approval state transitions
- auth and policy workflows

Prefer named actions that match implementation concepts, for example `Claim`, `Retry`, `Ack`,
or `GrantLease`.

Prefer small, named invariants:

- `AtMostOneHolder`
- `NoDoubleCharge`
- `AckedJobsStayOutOfQueue`
- `QuotaNeverNegative`

When a subsystem is arithmetic-heavy, keep TLA+ for the behavioral shell and move the arithmetic
corner into a Z3Py companion model referenced by `proof_obligations`.
