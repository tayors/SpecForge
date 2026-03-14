# Counterexample Reading

When `formal-check explain` renders a trace:

1. Start with the failing invariant or proof obligation id.
2. Note the backend that found it.
3. Read the action path if available.
4. Inspect the final state snapshot and the mapped code/test targets.
5. Turn the trace into a regression test before or alongside the fix.

If action labels are unavailable, do not infer them from business intuition alone. Use the state
sequence and mapped implementation files instead.
