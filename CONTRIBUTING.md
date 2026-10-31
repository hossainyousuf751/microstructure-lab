# Contributing to microstructure-lab

These rules keep code, tests, figures and the README in step with each other. They apply to
everyone who changes the repository, human or AI agent. If a rule gets in the way, change the
rule in a PR; don't quietly break it.

## Roles and responsibilities

| Role | Responsible for |
|---|---|
| **Maintainer** | Owns `main`, the roadmap and releases. Merges PRs, decides scope, bumps the version, keeps `CHANGELOG.md` honest. Final say on whether a result is good enough to publish in the README. |
| **Contributor** | Delivers one focused change per PR: code + tests + docs + regenerated figures. Runs the full check locally before asking for review. States in the PR which README numbers changed and why. |
| **Reviewer** | Checks correctness against the cited paper, not just that tests pass. Re-runs any example whose output the PR changes. Rejects PRs that weaken tests to go green. |
| **CI** (`.github/workflows/ci.yml`) | Lint + test on every push and PR, Python 3.10–3.13. A red CI blocks merge, no exceptions. |
| **AI agents** | Follow [AGENTS.md](AGENTS.md) and this file. Same bar as a human contributor; never commit or push without being asked. |

One person can hold several roles. On a one-person project the maintainer still reviews their own
PR against the checklist below before merging.

### Module ownership

Each module has one job. Put new code where its job is, or argue for a new module in the PR.

| Module | Responsibility | Must not |
|---|---|---|
| `book.py` | Order book state and exchange sequencing rules | Do I/O or networking |
| `recorder.py` | Talking to Binance, writing and loading recordings | Contain analytics |
| `simulator.py` | Synthetic order books with known ground truth | Depend on `features`/`analysis` |
| `features.py` | Per-update and per-bucket features from quotes/trades | Fit models |
| `analysis.py` | Regressions, forecasts, estimators | Plot or print |
| `market_making.py` | Quoting strategies and their simulations | Plot or print |
| `plotting.py` | Figures only; imports matplotlib lazily | Compute results the README relies on |
| `examples/` | Studies: run the library, print tables, save figures to `docs/` | Hold logic tests depend on |

Dependency direction: `examples → plotting → analysis/market_making → features → book/simulator`.
Nothing in `src/` imports from `examples/`.

## Workflow

1. **Pick or open an issue.** Roadmap items (M2, M3, …) are tracked in the README; anything
   bigger than a bug fix gets an issue first so two people don't build the same thing.
2. **Branch from `main`**: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `chore/<topic>`.
3. **Small PRs.** One concern each. A refactor and a behaviour change are two PRs.
4. **Commit messages**: imperative, ≤ 72-char subject, optional type prefix
   (`feat:`, `fix:`, `docs:`, `test:`, `chore:`). Body says *why*.
5. **Before pushing**, run the full check:

   ```bash
   ruff check .
   pytest
   ```

6. **Open a PR** using the checklist below. Squash-merge into `main`.
7. **Release**: maintainer moves `[Unreleased]` in `CHANGELOG.md` to a version and bumps
   `pyproject.toml` in a PR, then publishes a GitHub Release tagged `vX.Y.Z` on the merged
   commit. Publishing the release uploads that version to PyPI (`.github/workflows/publish.yml`);
   the workflow refuses a tag that doesn't match the package version. PyPI versions can't be
   replaced, so a mistake means a new patch release.

## Rules

### Code

- Python ≥ 3.10, `from __future__ import annotations` at the top of every module in `src/`.
- Line length 120; `ruff check .` must pass. Don't add `noqa` without a reason in the same line.
- Core dependencies are `numpy` and `pandas` only. Anything else goes in an optional extra
  (`plot`, `live`, `dev`) and is imported inside the function that needs it.
- Public functions are exported from `lobkit/__init__.py` and listed in `__all__`.
- Prefer vectorised numpy/pandas; plain Python loops are fine in the simulators, where event
  order matters.
- No new abstraction without a second user. A function beats a class until state is needed.

### Data formats

The whole library agrees on these column names. Don't invent synonyms.

- **quotes**: `ts` (seconds, float), `bid_px`, `bid_sz`, `ask_px`, `ask_sz`; one row per book update.
  Deeper levels, when present: `bid_px_2`, `bid_sz_2`, `ask_px_2`, `ask_sz_2`, … (level 1 keeps
  the plain names).
- **trades**: `ts`, `price`, `qty`, `side` (`+1` buyer-initiated, `−1` seller-initiated).
- Prices are in the instrument's units; the simulator uses ticks (`tick=1.0`).

### Research correctness

- **Cite the source.** Any model, formula or estimator names the paper (author, year,
  equation/section) in its docstring.
- **Every published number is reproducible.** A figure or table in the README must be produced by
  an `examples/` script with a fixed seed. If you change code that alters a published number,
  re-run the script and update the README in the same PR. Live-data results are the one
  exception (the data isn't committed): they name the recording session (symbol, date, length)
  and are labelled as one sample.
- **Every headline claim has a test.** If the README says "inventory management halves P&L
  volatility", a test asserts it with a tolerance. Tolerances reflect Monte Carlo error, not
  wishful thinking; loosening one needs a sentence of justification in the PR.
- **Validate on the simulator first.** New analytics run on `simulate_lob` (known ground truth)
  before they are pointed at live data.
- **Out-of-sample means chronological.** No shuffled splits on time series.

### Tests

- `pytest` must stay fast (under ~30 s locally). Mark anything slower with `@pytest.mark.slow`.
- Hand-computed cases for formulas, property tests (invariants) for simulators, published-value
  tests for replications.
- Never delete, skip or weaken a test to make a change pass. Fix the code or explain in the PR
  why the test was wrong.
- No network in tests. Live-data code is tested with recorded fixtures or synthetic events.

### Data and secrets

- Recordings live in `data/` (gitignored). Never commit market data.
- No API keys are needed; if that ever changes, they come from environment variables, never
  from source.

### Docs

- `README.md` is the paper: results, figures, method. `CHANGELOG.md` is the history.
- Figures in `docs/` are generated, never hand-edited. Regenerate rather than patch.
- Roadmap checkboxes are ticked in the PR that completes the milestone.

## Pull request checklist

```markdown
- [ ] One concern; branch name and title describe it
- [ ] `ruff check .` and `pytest` pass locally
- [ ] New/changed behaviour has a test; no test was weakened
- [ ] Models cite their paper in the docstring
- [ ] README numbers/figures regenerated if they changed (say which)
- [ ] CHANGELOG.md `[Unreleased]` updated
```
