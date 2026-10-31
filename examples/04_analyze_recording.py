"""Run the same study on a live recording.

Usage: python 04_analyze_recording.py ../data/btcusdt_<stamp> [tick]
tick is the instrument's price increment (0.01 for BTCUSDT spot).
"""

import sys
from pathlib import Path

from _study import run_multi_level, run_study

from lobkit.recorder import load_depth, load_recording

path = Path(sys.argv[1])
tick = float(sys.argv[2]) if len(sys.argv) > 2 else 0.01
label = "Binance " + path.name.split("_")[0].upper()
quotes, trades = load_recording(path)
run_study(quotes, trades, label, freq="1s", unit="USDT", tick=tick)
run_multi_level(load_depth(path), label + " depth", freq="5s")     # depth is sampled once a second
