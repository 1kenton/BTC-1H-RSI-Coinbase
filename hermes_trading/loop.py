"""
RSI Mean-Reversion strategy — BTC/USD 1-hour chart on Coinbase.

Rules (from state/strategy.yaml):
  Entry : RSI(period) drops below entry_threshold (default 30) — open long.
  Exit  : RSI rises above exit_threshold (default 70) on closed candle — close long.
  Stop  : stop_loss_pct below entry price (default 1.8%).
  Filter: Only one open trade at a time.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from hermes_trading.adapters.price import fetch_ohlcv

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

STATE_FILE    = Path("state/worker_state.json")
TRADES_FILE   = Path("state/trades.jsonl")
STRATEGY_FILE = Path("state/strategy.yaml")
GOAL_FILE     = Path("state/goal.yaml")

GRANULARITY = 3600   # 1-hour candles
TICK_SLEEP  = 300    # re-check every 5 minutes


def load_params() -> dict:
    try:
        raw = yaml.safe_load(STRATEGY_FILE.read_text()) or {}
        return {
            "rsi_period":        int(raw.get("entry", {}).get("rsi_period", 14)),
            "entry_threshold": float(raw.get("entry", {}).get("rsi_entry_threshold", 30.0)),
            "exit_threshold":  float(raw.get("entry", {}).get("rsi_exit_threshold",  70.0)),
            "stop_loss_pct":   float(raw.get("stop_loss_pct", 1.8)) / 100,
        }
    except Exception:
        return {"rsi_period": 14, "entry_threshold": 30.0,
                "exit_threshold": 70.0, "stop_loss_pct": 0.018}


def reflection_due() -> bool:
    try:
        goal = yaml.safe_load(GOAL_FILE.read_text()) or {}
    except Exception:
        goal = {}
    every = int(goal.get("reflection_every", 5))
    if not TRADES_FILE.exists():
        return False
    count = sum(1 for line in TRADES_FILE.read_text().splitlines() if line.strip())
    return count > 0 and count % every == 0


def load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"current_trade": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def log_trade(record: dict) -> None:
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def calc_rsi(closes: list, period: int = 14) -> float | None:
    """Wilder-smoothed RSI. Returns current RSI value or None if not enough data."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    avg_g  = sum(gains[:period]) / period
    avg_l  = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)


async def loop_once(state: dict) -> dict:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    p = load_params()

    candles = await fetch_ohlcv(granularity=GRANULARITY, limit=100)
    if len(candles) < p["rsi_period"] + 5:
        logger.warning(f"Only {len(candles)} candles — need {p['rsi_period']+5}+, skipping")
        return state

    completed = candles[:-1]   # exclude in-progress candle
    last      = completed[-1]
    closes    = [c["close"] for c in completed]
    price     = last["close"]
    rsi       = calc_rsi(closes, p["rsi_period"])

    if rsi is None:
        logger.info("RSI not ready yet")
        return state

    # ── exit / manage open trade ────────────────────────────────────────────────
    if state["current_trade"]:
        trade  = state["current_trade"]
        sl     = trade["stop_loss"]
        closed = None

        if last["low"] <= sl:
            pnl    = (sl - trade["entry_price"]) / trade["entry_price"]
            closed = {**trade, "exit_price": sl, "exit_reason": "sl",
                      "pnl_pct": round(pnl, 6), "close_ts": now_ts}
        elif rsi >= p["exit_threshold"]:
            pnl    = (price - trade["entry_price"]) / trade["entry_price"]
            closed = {**trade, "exit_price": round(price, 2), "exit_reason": "rsi_exit",
                      "pnl_pct": round(pnl, 6), "close_ts": now_ts}

        if closed:
            log_trade(closed)
            logger.info(
                f"CLOSED | entry={closed['entry_price']:.2f} "
                f"exit={closed['exit_price']:.2f} reason={closed['exit_reason']} "
                f"pnl={closed['pnl_pct']*100:.3f}% | RSI={rsi:.1f}"
            )
            state["current_trade"] = None
            if reflection_due():
                logger.info("Reflection triggered")
                try:
                    from hermes_trading.reflect import run_reflection
                    run_reflection()
                except Exception as e:
                    logger.error(f"Reflection failed: {e}")
        else:
            logger.info(
                f"OPEN long @ {trade['entry_price']:.2f} "
                f"SL={sl:.2f} | price={price:.2f} RSI={rsi:.1f}"
            )
        return state

    # ── entry check ─────────────────────────────────────────────────────────────
    if rsi < p["entry_threshold"]:
        sl = round(price * (1 - p["stop_loss_pct"]), 2)
        state["current_trade"] = {
            "direction": "long",
            "entry_price": round(price, 2),
            "stop_loss": sl,
            "entry_ts": now_ts,
            "open_ts": now_ts,
            "mode": "paper",
            "entry_rsi": round(rsi, 2),
        }
        logger.info(
            f"ENTRY long @ {price:.2f} SL={sl:.2f} | "
            f"RSI={rsi:.1f} < {p['entry_threshold']}"
        )
    else:
        logger.info(
            f"Waiting | price={price:.2f} RSI={rsi:.1f} "
            f"(entry<{p['entry_threshold']} exit>{p['exit_threshold']})"
        )

    return state


async def loop_forever() -> None:
    logger.info("Booting hermes-trading worker | BTC-1H-RSI-Coinbase")
    logger.info("Strategy: RSI mean-reversion | buy<30 sell>70 | 1H candles")
    state = load_state()
    tick  = 0
    while True:
        tick += 1
        logger.info(f"[{datetime.now(timezone.utc).isoformat()}] Tick {tick}")
        try:
            state = await loop_once(state)
            save_state(state)
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
        await asyncio.sleep(TICK_SLEEP)
