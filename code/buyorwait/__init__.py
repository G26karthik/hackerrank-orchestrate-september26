"""Buy or Wait? -- deterministic decision pipeline package.

Stage 2 status (see evaluation/state.md for the authoritative record):

  REAL, implemented and tested this stage:
    decimal_utils, schemas, fx, io_load, csv_format, writer, simulator,
    independent_verifier, metering

  INTERFACE STUBS -- typed dataclasses and function signatures only, every
  callable raises NotImplementedError, ready for Stage 3/4 to implement:
    evidence, resolver, recurrence, forecast, planner, explain, llm_harness

Nothing in the stub modules is wired into `main.py`'s runnable path, and
`main.py` does not claim to produce `output.csv` yet -- see its module
docstring.
"""
