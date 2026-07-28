# pi_mono.evals

Placeholder for the TypeScript `packages/evals` vitest harness.

The TS eval harness uses vitest fixtures, provider mocking, and
`packages/coding-agent/test/suite/harness.ts` to run structured model
evaluations.  That infrastructure has **not been ported to Python** yet.

This package exports a stub `EvalHarness` class so downstream code can
reference it without import errors.  Calling `EvalHarness.run()` raises
`NotImplementedError`.

## When will this be ported?

No timeline.  If you need Python-native evals, build on pytest and the
faux provider in `python/tests/` for now.
