# Instructions for AI coding agents

Read [CONTRIBUTING.md](CONTRIBUTING.md) first; its rules apply to you in full. This file adds
what an agent needs to work safely in this repo.

## Setup and checks

```bash
python -m venv .venv && .venv/Scripts/activate      # or: source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest
```

Run both checks before you report a task as done, and report their real output.

## Ground rules

- **Stay in your lane.** Respect the module ownership table in CONTRIBUTING.md. If a task needs a
  module boundary changed, say so instead of doing it silently.
- **Don't fake results.** Numbers in `README.md` come only from running `examples/*.py`. Never
  type a number into the README that you didn't just produce, and never edit a figure by hand.
- **Don't weaken the bar.** No skipped/deleted tests, loosened tolerances, or `noqa` to get green.
- **Keep the column contract** (`ts, bid_px, bid_sz, ask_px, ask_sz`; trades `ts, price, qty, side`).
- **No network in tests**, no new core dependencies, no committed data.
- **Git:** don't commit, push, tag or open PRs unless the user asks. Never force-push `main`.
- **Leave a trail.** Update `CHANGELOG.md` `[Unreleased]` for any user-visible change.

## Where things are

- Library: `src/lobkit/` · Tests: `tests/` · Studies: `examples/` (run from repo root or `examples/`)
- Example runtime: `01` ~10 s, `02` ~5 s, `05` ~45 s, `06` ~10 s; `03` records live data for N seconds
  (needs `.[live]`); `04` and `06` take a recording folder from `data/`.
- Windows consoles use cp1252: keep `print()` output to characters it can encode (`²` works; `√` and Greek letters don't).
  Plot titles and labels are not affected.
