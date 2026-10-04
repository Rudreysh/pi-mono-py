# pi_mono.evals

Python eval harness for running named cases against a completion callback.

This is not a port of the TypeScript vitest plugin. It covers the case-runner
shape used by `packages/evals`: add cases, run them, collect pass/fail plus
duration. Wire a faux provider or any async complete function.
