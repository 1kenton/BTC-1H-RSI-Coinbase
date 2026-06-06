"""
Reflection cycle: after every N closed trades, call Claude to propose ONE strategy tweak.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

STRATEGY_FILE    = Path("state/strategy.yaml")
TRADES_FILE      = Path("state/trades.jsonl")
GOAL_FILE        = Path("state/goal.yaml")
HYPOTHESES_FILE  = Path("state/hypotheses.jsonl")

TUNABLE = [
    "entry.rsi_period",
    "entry.rsi_entry_threshold",
    "entry.rsi_exit_threshold",
    "stop_loss_pct",
]


def _load_recent_trades(n: int = 25) -> list:
    if not TRADES_FILE.exists():
        return []
    lines = [l for l in TRADES_FILE.read_text().splitlines() if l.strip()]
    return [json.loads(l) for l in lines[-n:]]


def _summarise(trades: list) -> str:
    if not trades:
        return "No trades yet."
    wins   = [t for t in trades if t.get("pnl_pct", 0) > 0]
    losses = [t for t in trades if t.get("pnl_pct", 0) <= 0]
    avg_pnl = sum(t.get("pnl_pct", 0) for t in trades) / len(trades)
    return (
        f"Last {len(trades)} trades: {len(wins)} wins / {len(losses)} losses | "
        f"avg PnL {avg_pnl*100:.3f}%"
    )


def run_reflection() -> bool:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping reflection")
        return False

    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed")
        return False

    trades   = _load_recent_trades(25)
    summary  = _summarise(trades)
    strategy = yaml.safe_load(STRATEGY_FILE.read_text()) if STRATEGY_FILE.exists() else {}

    try:
        goal_text = GOAL_FILE.read_text() if GOAL_FILE.exists() else "Maximise risk-adjusted returns."
    except Exception:
        goal_text = "Maximise risk-adjusted returns."

    prompt = f"""You are a systematic trading strategy optimizer.

Goal: {goal_text}

Performance: {summary}

Current strategy (strategy.yaml):
{yaml.dump(strategy, default_flow_style=False)}

Tunable parameters (change only ONE):
{chr(10).join(f"  - {k}" for k in TUNABLE)}

Respond with ONLY valid JSON in this exact format:
{{
  "variable": "<dot.path.to.param>",
  "old_value": <current_numeric_value>,
  "new_value": <proposed_numeric_value>,
  "reasoning": "<one sentence>"
}}"""

    try:
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        suggestion = json.loads(raw)
    except Exception as e:
        logger.error(f"Anthropic call failed: {e}")
        return False

    var  = suggestion.get("variable", "")
    nval = suggestion.get("new_value")
    if var not in TUNABLE or nval is None:
        logger.warning(f"Ignoring invalid suggestion: {suggestion}")
        return False

    # Apply change to strategy.yaml
    keys = var.split(".")
    node = strategy
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = nval

    # Bump version
    try:
        ver = int(strategy.get("version", "01")) + 1
        strategy["version"] = str(ver).zfill(2)
    except Exception:
        pass

    STRATEGY_FILE.write_text(yaml.dump(strategy, default_flow_style=False))

    record = {
        "ts": datetime.utcnow().isoformat(),
        "trades_analyzed": len(trades),
        **suggestion,
    }
    HYPOTHESES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HYPOTHESES_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

    logger.info(
        f"Reflection: {var} {suggestion.get('old_value')} → {nval} | "
        f"{suggestion.get('reasoning', '')}"
    )
    return True
