"""
Reflection cycle: analyzes trades and proposes ONE strategy change.
"""
import json
import yaml
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

def reflect(trades: list, strategy_path: str = "state/strategy.yaml") -> dict:
    """
    Analyze N trades and propose ONE variable change.
    
    Args:
        trades: List of trade dicts with pnl, entry_price, exit_price, etc.
        strategy_path: Path to current strategy.yaml
    
    Returns:
        dict with hypothesis: {variable, old_value, new_value, reason}
    """
    if not trades or len(trades) < 5:
        return {"status": "waiting", "trades_count": len(trades)}
    
    # Load current strategy
    if not Path(strategy_path).exists():
        strategy_path = f"/app/{strategy_path}"
    
    with open(strategy_path) as f:
        strategy = yaml.safe_load(f)
    
    # Analyze trades
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0
    
    # Simple hypothesis: if win rate < 50%, tighten entry (raise RSI threshold)
    hypothesis = None
    if win_rate < 0.5 and avg_loss < 0:
        hypothesis = {
            "variable": "entry.threshold",
            "old_value": strategy.get("entry", {}).get("threshold", 30),
            "new_value": 35,
            "reason": f"Win rate {win_rate:.1%} below 50%, raising RSI entry threshold",
        }
    
    return {
        "status": "proposed" if hypothesis else "waiting",
        "trades_analyzed": len(trades),
        "win_rate": win_rate,
        "hypothesis": hypothesis,
    }
