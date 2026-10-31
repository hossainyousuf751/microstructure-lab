# microstructure-lab

[![tests](https://github.com/hossainyousuf751/microstructure-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/hossainyousuf751/microstructure-lab/actions/workflows/ci.yml) [![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/hossainyousuf751/microstructure-lab/blob/main/LICENSE)

Limit order book reconstruction, order-flow analytics, and market-making simulation.
The analytics are validated on a zero-intelligence order book simulator, then run unchanged
on live Binance data.

The library alone, from PyPI:

```bash
pip install lobkit              # add [plot] for figures, [live] to record exchange data
```

The studies below live in this repository, so to reproduce them clone it and run:

```bash
pip install -e ".[dev]"
ruff check . && pytest
cd examples
python 01_simulated_lob.py           # order-flow analytics on a simulated book       (~10 s)
python 02_avellaneda_stoikov.py      # market-making replication                      (~5 s)
python 05_market_making_in_lob.py    # the market maker inside the simulated book     (~45 s)
pip install -e "..[live]"
python 03_record_binance.py btcusdt 900       # record 15 minutes of Binance + Bybit data
python 04_analyze_recording.py ../data/btcusdt_<timestamp> 0.01    # 0.01 = tick size
python 06_cross_venue.py ../data/btcusdt_<timestamp>               # which venue leads?
```

## Components

| Module | What it does |
|---|---|
| `book.py` | L2 order book; Binance diff-depth synchronisation with sequence-gap detection |
| `recorder.py` | Async recorder for Binance best quotes, trades and synchronised L2 depth, plus Bybit best quotes and trades; auto-reconnect; loaders |
| `simulator.py` | Zero-intelligence limit order book (Cont, Stoikov & Talreja 2010), optional multi-level output and a resting quoter with queue position |
| `features.py` | Mid, spread, queue imbalance, microprice, order-flow imbalance (OFI, single and multi-level), time buckets |
| `analysis.py` | Price-impact regressions, impact vs depth, out-of-sample predictability, Stoikov micro-price, cross-venue lead-lag |
| `market_making.py` | Avellaneda–Stoikov optimal market maker vs a symmetric benchmark, in the paper's model and inside the order book |

See [CONTRIBUTING.md](https://github.com/hossainyousuf751/microstructure-lab/blob/main/CONTRIBUTING.md) for the rules, roles and workflow, and
[CHANGELOG.md](https://github.com/hossainyousuf751/microstructure-lab/blob/main/CHANGELOG.md) for what changed.

**Book synchronisation.** Binance publishes a REST snapshot plus a diff stream. A correct
local book has to drop diffs already in the snapshot, check that the first applied diff
bridges the snapshot's update ID, and verify every later diff continues the sequence exactly.
`BinanceDepthSync` implements these rules, raises `SequenceGap` on a missed update, and the
recorder resyncs automatically. Each rule has a unit test.

## Study 1: order flow and prices

On 4.6 simulated hours (400,000 book events) of a market where no participant has information:

| Result | Value | Literature |
|---|---|---|
| Δmid on OFI, 10-second buckets | β = 0.285 ticks per unit, **R² = 0.66**, t = 56 | Cont, Kukanov & Stoikov (2014): average R² ≈ 65% on US stocks |
| Impact coefficient vs 1/depth | linear, R² = 0.93 | β inversely proportional to depth |
| P(next move up), imbalance 0.1–0.2 → 0.8–0.9 | 0.25 → 0.79, monotone | Gould & Bonart (2016) |
| Next 10-second move from OFI / imbalance | out-of-sample R² ≤ 0.7% | — |
| Δmid on OFI of the best 1 → 5 levels, 10 s | out-of-sample R² 0.66 → 0.79 → 0.85 → 0.86 → **0.88** | Xu, Gould & Howison (2019) |
| Forecast of the mid after the next mid change | Stoikov micro-price −6.6% MSE vs mid; naive microprice −1.3% | Stoikov (2018) |

![OFI impact](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/simulated_lob_ofi_impact.png)

![Impact vs depth](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/simulated_lob_impact_depth.png)

**Explaining is not predicting.** Order flow explains two-thirds of price changes in the same
interval but almost none of the next 10 seconds. Queue imbalance strongly predicts the *next*
price move, but in a liquid book many moves happen within a 10-second bucket. The edge is real
at the event horizon, and only accessible to someone fast enough to act on it.

![Queue imbalance](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/simulated_lob_queue_imbalance.png)

**Deeper order flow matters.** Best-level OFI misses flow that arrives one level back and becomes
the best queue a moment later. Adding the second level lifts out-of-sample R² from 0.66 to 0.79,
and five levels reach 0.88. In-sample and out-of-sample R² agree, so this is not overfitting.

![Multi-level OFI](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/simulated_lob_multi_level_ofi.png)

**The naive microprice overshoots; Stoikov's micro-price doesn't.** The imbalance-weighted mid is
a worse forecast of the very next mid than the mid itself (−82% at one update, out of sample), and
only marginally better at 10–100 updates. With small queues it over-reacts to imbalance.
Stoikov's (2018) micro-price is estimated as a Markov chain on (spread, imbalance): fitted on the
first 70% of the data, it shades the mid by at most 0.29 ticks at a one-tick spread, against 0.36
for the naive formula in the same bucket, and much less when the spread is two ticks. It is built
to forecast the mid at the next *price changes*, and there it wins clearly: 6.6% lower squared
error than the mid for the next change, and 4.2% for the one after, against 1.3% and 2.6% for the
naive microprice. At one book update it still loses to the mid (−18%), because most updates
don't move the price at all.

![Micro-price](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/simulated_lob_microprice.png)

One detail matters for the estimator: with small integer queues a perfectly balanced book
(imbalance exactly 0.5) is common. With the usual 10 imbalance buckets those states land in an
"up" bucket and break the symmetry the method relies on, so lobkit uses an odd number (11).

## Study 2: Avellaneda–Stoikov market making

The market maker quotes around a reservation price r = s − qγσ²(T − t), shifted against its
inventory q, with the optimal spread γσ²(T − t) + (2/γ)ln(1 + γ/k). The symmetric benchmark uses
the same spread centred on the mid. Paper parameters: s₀ = 100, σ = 2, T = 1, dt = 0.005,
A = 140, k = 1.5, 4,000 simulations:

| γ | Strategy | Mean P&L | Std P&L | Std final inventory |
|---|---|---|---|---|
| 0.01 | inventory | 66.8 | 8.9 | 5.4 |
| 0.01 | symmetric | 67.1 | 13.8 | 9.0 |
| **0.1** | **inventory** | **63.4** | **6.4** | **3.0** |
| **0.1** | **symmetric** | **66.8** | **13.1** | **8.6** |
| 0.5 | inventory | 47.3 | 5.8 | 2.0 |
| 0.5 | symmetric | 57.7 | 11.6 | 7.2 |

The paper reports approximately 62.9 (std 5.9) and 67.2 (std 13.4) for γ = 0.1. Inventory
management halves P&L volatility and keeps inventory three times tighter, for about 5% less profit.

![Avellaneda-Stoikov](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/avellaneda_stoikov.png)

**A finding along the way.** My first implementation evaluated fills before moving the mid within
each time step, and gave 65.1 for the inventory strategy, about 2 above the paper and outside
Monte Carlo error. Moving the mid first, then evaluating fills against quotes set before the
move, reproduces the paper. It is also the more realistic ordering: it captures adverse
selection, where quotes the price has moved through are more likely to fill.

## Study 3: live Binance data

`03_record_binance.py` records best quotes, trades and synchronised L2 depth for any spot pair;
`04_analyze_recording.py` runs the same analysis as Study 1 at 1-second buckets, plus multi-level
OFI on the recorded top-10 depth (sampled once a second, so 5-second buckets). Comparing the
simulated and live tables shows which effects are mechanical consequences of the order book
and which require informed traders. Record at least 15 minutes; the script warns when there is
too little data to say anything.

Results for one session: BTCUSDT, 40 minutes on 2026-11-01 from 03:18 local time (76,296 quote
updates, 5,813 trades). It was a quiet market: the price stayed within a 181 USDT range and the
mid changed 688 times, about once every 3.5 seconds. That session is one sample, not a study, and
the recording is not in the repository (market data is never committed), so treat these numbers
as an illustration of the pipeline.

| Result | Live, 1 s buckets | Simulated |
|---|---|---|
| Δmid on OFI | β = 0.221 USDT per unit, **R² = 0.56**, t = 55 | R² = 0.42 at 1 s (Study 5), 0.66 at 10 s |
| Impact coefficient vs 1/depth | R² = 0.85 across depth quintiles | R² = 0.93 (10 s) |
| P(next move up), imbalance < 0.1 → > 0.9 | 0.38 → 0.97, not monotone in between | monotone |
| Next 1 s move from queue imbalance | out-of-sample R² 3.3% | 0.7% (next 10 s) |
| Multi-level OFI, best 1 → 10 levels (5 s) | out-of-sample R² 0.50 → 0.40–0.49: no gain | 0.66 → 0.88, 1 → 5 levels (10 s) |
| Micro-price vs mid, next price change | Stoikov −0.34% MSE, naive −0.32%: no real edge | Stoikov −6.6%, naive −1.3% |

![Binance OFI impact](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/binance_btcusdt_ofi_impact.png)

**What survives contact with a real book.** The contemporaneous OFI relation is at least as
strong live as in the simulator at 1-second buckets, and impact is still larger when the book is
thin. Queue imbalance predicts the next move at the extremes, and on the live book it even has a
little out-of-sample power over the next second.

**What doesn't.** Deeper levels add nothing out of sample, while they explained a lot in the
simulator. On BTCUSDT the levels behind the best quote are a cent apart and mostly small resting
orders, so their flow carries little information. Neither micro-price beats the mid by more than
a third of a percent. Most rows sit at a one-tick spread with the price unchanged. The 688 price
changes include 323 updates where one side of the book thinned out for an instant and the spread
jumped past 1 USDT (up to 10.8), and a squared-error comparison over so few moves is decided by
those points. A busier session, or a robust loss, is the next step.

## Study 4: the market maker inside the order book

Study 2 assumes fills arrive at rate A·e^(−kδ), independent of what the price does next. In a real
book an order fills only when market orders have eaten the queue ahead of it, which is exactly
when the price is about to move through it. `05_market_making_in_lob.py` puts the same quoter
into the zero-intelligence book: one unit per side, joining the back of the queue, keeping its
place if the quote doesn't change at the once-a-second requote, and filling only when a market
order reaches it.

The paper's inputs are calibrated on the book itself: σ = 1.08 ticks/√s from 1-second mid
changes; A = 0.59 fills/s and k = 1.39 per tick from a quoter resting at fixed distances from the
mid. Episodes last T = 300 s, 200 per row:

| γ | Strategy | Mean P&L | Std P&L | Std final inventory | Fills | Spread captured | Adverse sel. 1 s | Adverse sel. 10 s | Kept |
|---|---|---|---|---|---|---|---|---|---|
| 0.001 | inventory | 30.1 | 25.9 | 4.0 | 71 | 0.82 | −0.21 | −0.30 | 63% |
| 0.001 | symmetric | 46.5 | 58.3 | 7.2 | 70 | 0.84 | −0.18 | −0.17 | 80% |
| **0.005** | **inventory** | **19.4** | **13.3** | **2.4** | **64** | **0.79** | **−0.30** | **−0.48** | **39%** |
| **0.005** | **symmetric** | **28.9** | **59.0** | **6.9** | **51** | **0.88** | **−0.19** | **−0.20** | **77%** |
| 0.02 | inventory | 8.0 | 7.5 | 1.4 | 26 | 0.81 | −0.35 | −0.53 | 35% |
| 0.02 | symmetric | 14.5 | 25.9 | 4.1 | 18 | 0.96 | −0.20 | −0.17 | 82% |

(P&L in ticks; spread captured and adverse selection in ticks per fill; "kept" is after 10 s. Markouts
leave out fills too close to the end of an episode to have a full horizon.)

**Inventory control still works.** The skewed quoter cuts P&L volatility by 2.3–4.4× and final
inventory by 1.8–2.9×, as in the paper.

**But it pays for it in adverse selection.** Every fill captures 0.79–0.96 ticks against the mid
at that moment. Ten seconds later the symmetric quoter has given back about a fifth of that; the
inventory quoter gives back 37–65%. To unload inventory it quotes aggressively on one side, often
alone at a new best price, and an order alone at the front is the first to be hit when the price
moves. As a result inventory control costs 33–45% of mean P&L here, against about 5% in the
paper's model (Study 2), where a fill says little about the next price move.

**The two costs have different clocks.** The symmetric quoter's loss is complete within a second
(−0.17 to −0.21 ticks at both horizons): it is the tick the price jumps when the quoter's queue
is used up. The inventory quoter loses −0.21 to −0.35 in the first second and keeps losing until
−0.30 to −0.53 at ten seconds, so its fills come before sustained moves, not just a one-tick jump.

![AS in the LOB](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/as_in_lob.png)

## Study 5: which venue moves first?

`06_cross_venue.py` compares the Binance and Bybit BTCUSDT books recorded in the same session,
on one local clock. `lead_lag` correlates the two venues' mid returns at lags of ±2 s on a 50 ms
grid; `cross_venue_impact` asks how much of each venue's 1-second price change its own and the
other venue's order flow explain, and whether either venue's flow or return predicts the other's
*next* second. Following the repo's rule, the estimators are first run where the answer is
known: a simulated venue B that copies venue A 300 ms late. They find the delay exactly
(correlation 1.00 at +300 ms) and the direction: only B's next move is predictable from A.

Same session as Study 3 (40 minutes; 76,296 Binance and 24,969 Bybit quote updates):

| Target venue | R² own OFI | R² other venue's OFI | R² both | Next 1 s from other's OFI (OOS) | Next 1 s from other's return (OOS) |
|---|---|---|---|---|---|
| Binance | 0.56 | 0.16 | 0.56 | 0.014 | 0.009 |
| Bybit | 0.58 | 0.28 | 0.60 | 0.004 | 0.004 |

![Lead-lag](https://raw.githubusercontent.com/hossainyousuf751/microstructure-lab/main/docs/cross_venue_lead_lag.png)

**No exploitable lead at this resolution.** Returns are most correlated at 0 ms (0.09): the
venues move within the same 50 ms. Each venue's own order flow explains its price far better than
the other's. Neither venue's flow or return predicts the other's next second by more than about
1% out of sample. There is more correlation at negative lags (Bybit first, summed 0.62 against
0.20 for Binance first), and it persisted after the recorder's timestamp bug was fixed (see
CHANGELOG), but Bybit's price changed only 218 times, so this is a hypothesis for a longer
recording, not a finding. One limitation is built in: timestamps are local receive times, so each
venue's network latency to the recording machine is part of the measured lag. A lead shorter than
the difference in latencies can't be seen from one machine.

## Roadmap

- [x] **M1** Book sync, recorder, ZI simulator, OFI/imbalance analytics, Avellaneda–Stoikov replication
- [x] **M2** Multi-level OFI (Xu, Gould & Howison 2019) using the recorded L2 depth
- [x] **M3** Stoikov (2018) micro-price, estimated as a Markov chain on (imbalance, spread)
- [x] **M4** Run the Avellaneda–Stoikov quoter inside the order book simulator, with queue position and adverse selection
- [x] **M5** Cross-venue study: OFI and lead-lag between Binance and a second exchange (Bybit)

## References

- Avellaneda, M. & Stoikov, S. (2008). High-frequency trading in a limit order book. *Quantitative Finance* 8(3).
- Cont, R., Stoikov, S. & Talreja, R. (2010). A stochastic model for order book dynamics. *Operations Research* 58(3).
- Cont, R., Kukanov, A. & Stoikov, S. (2014). The price impact of order book events. *Journal of Financial Econometrics* 12(1).
- Gould, M. & Bonart, J. (2016). Queue imbalance as a one-tick-ahead price predictor in a limit order book. *Market Microstructure and Liquidity* 2(2).
- Stoikov, S. (2018). The micro-price: a high-frequency estimator of future prices. *Quantitative Finance* 18(12).
- Xu, K., Gould, M. D. & Howison, S. D. (2019). Multi-level order-flow imbalance in a limit order book. *Market Microstructure and Liquidity* 4(3–4).
