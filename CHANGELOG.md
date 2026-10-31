# Changelog

All notable changes to this project. Versions follow [Semantic Versioning](https://semver.org/)
(0.x: minor bumps may break the API). From 0.2.2 on, entries are written by release-please from
the conventional titles of merged PRs; don't edit this file by hand.

## [0.2.1] - 2026-11-01

First release on PyPI (`pip install lobkit`). No change to the library's behaviour.

### Added
- Publishing to PyPI: `.github/workflows/publish.yml` builds, checks and uploads the package
  when a GitHub Release is published, via PyPI trusted publishing (no stored token). It refuses
  to publish if the release tag does not match the version in `pyproject.toml`.
- Package metadata for PyPI: SPDX license, classifiers, keywords and project URLs. CI builds the
  package and runs `twine check --strict` on every push.

### Changed
- README links are absolute so images and links render on PyPI.
- CI uses `actions/checkout@v7` and `actions/setup-python@v7` (Node 24); v4/v5 ran on the deprecated Node 20.

## [0.2.0] - 2026-11-01

### Added
- **M2** Multi-level OFI (Xu, Gould & Howison 2019): `multi_level_ofi`, `multi_level_impact`;
  `simulate_lob(n_levels=...)` records the best N non-empty levels; `recorder.load_depth` turns
  recorded L2 depth into the same wide format; `bucket_features` sums any `ofi_<m>` columns.
- **M3** Stoikov (2018) micro-price: `estimate_microprice` returns a `MicroPrice` that maps
  (spread, imbalance) states to an adjustment of the mid.
- **M4** Market making inside the order book: `simulate_lob(quoter=..., requote_every=..., t_end=...)`
  rests a quoter's orders with real queue position; `market_making.as_quoter`, `simulate_as_lob`
  (spread capture / adverse selection decomposition) and `fill_intensity` (calibrates A and k).
- **M5** Cross-venue study: `lead_lag` (cross-correlation of mid returns across venues) and
  `cross_venue_impact` (own vs other venue's OFI, next-bucket predictability); validated on a
  simulated venue pair with a known 300 ms delay.
- Bybit recording alongside Binance in the same session and clock (`record_binance(..., bybit=True)`,
  on by default in `03_record_binance.py`); `load_recording(path, venue=...)`.
- Recorder reconnects automatically after a dropped websocket (Binance depth book resynchronised).
- `simulate_as_lob` reports adverse selection at several markouts (`adverse_1s`, `adverse_10s`).
- `examples/05_market_making_in_lob.py` (Study 4), `examples/06_cross_venue.py` (Study 5), and
  figures for M2–M5.
- MIT `LICENSE`; README badges.
- `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, this changelog.
- Ruff lint in `pyproject.toml` and CI; CI on Python 3.13 with pip caching.
- Tests for the recording loaders, empty buckets, multi-level OFI, micro-price and the quoter.

### Changed
- `microprice_forecast_error` takes `predictors` and `clock` ("updates" or "moves"); output
  columns are now `horizon_<clock>`, `mse_<p>`, `improvement_<p>_pct` (was `improvement_pct`).
- `ASResult` is exported from `lobkit`.
- `load_recording` stamps trades with their local receive time (`ts_local`), the clock the quotes
  use; the exchange time was up to ~1.5 s off the local clock and misaligned trade buckets.
- `examples/04_analyze_recording.py` takes the tick size and also runs multi-level OFI on the depth.

### Fixed
- Recorder crashed if a `SequenceGap` was raised while replaying buffered diffs onto a new
  snapshot, or if the REST snapshot request failed; it now resyncs, and retries failed
  snapshots after 5 s instead of hammering the API.
- `bucket_features`: an empty time bucket made the next bucket's `d_mid` NaN, silently dropping it.
- Bybit recorder kept the previous best price when a snapshot arrived with one side empty,
  recording a stale quote; the exchange message parsing is now in pure functions with tests.
- Recorder stamped each message with the clock read *before* waiting for it, i.e. roughly the
  previous message's arrival time; on a sparse stream such as Bybit's this made quotes look early
  by about one inter-message gap. Messages are now stamped on arrival. Live results were re-recorded.
- `bucket_features` dropped empty buckets, so "next bucket" in `predictive_r2` and
  `cross_venue_impact` could be several intervals ahead on sparse data. Empty buckets are now kept
  with zero flow and the book state carried forward (no change to simulated results).
- `MicroPrice` crashed on a NaN imbalance (empty book); such rows now get no adjustment.
- `simulate_as_lob` markouts for fills near the end of an episode used the final mid; those fills
  are now left out of that horizon.
- Recorder left an orphaned snapshot task after a sequence gap; it is now cancelled.
- Simulator: float rounding in cancel selection could cancel from an empty queue (negative size).
- `simulate_as` crashed when `n_paths < keep_paths`.
- Examples: `03` wrote to `../data` relative to the working directory; `04` parsed the
  recording name with `/`, which broke on Windows paths.

## [0.1.0]

- **M1** Book sync, recorder, zero-intelligence simulator, OFI/imbalance analytics,
  Avellaneda–Stoikov replication.
