"""Record live Binance (and Bybit) data. Usage: python 03_record_binance.py btcusdt 900 [--binance-only]"""

import asyncio
import sys
from pathlib import Path

from lobkit.recorder import record_binance

args = [a for a in sys.argv[1:] if not a.startswith("--")]
symbol = args[0] if args else "btcusdt"
seconds = int(args[1]) if len(args) > 1 else 900
asyncio.run(record_binance(symbol, seconds, out_dir=Path(__file__).resolve().parent.parent / "data",
                           bybit="--binance-only" not in sys.argv))
