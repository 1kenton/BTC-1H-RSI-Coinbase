"""
Scoring function: evaluates trade outcomes against goal.yaml
Returns composite score in [-1, +1]
"""
import yaml
import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def load_goal(goal_path: str = "state/goal.yaml") -> dict:
    """Load goal thresholds from YAML"""
    if not Path(goal_path).exists():
        goal_path = f"/app/{goal_path}"
    with open(goal_path) as f:
        return yaml.safe_load(f)

def score(trades: list, goal: dict) -> float:
    """
    Score a batch of trades against goals.
    
    Returns:
      float in [-1, +1] where:
        +1 = exceeds all goals
         0 = meets minimum goals
        -1 = fails hard stop
    """
    if not trades:
        return 0.0
    
    # Calculate metrics
    returns = [t.get("pnl", 0) for t in trades]
    total_return = sum(returns)
    avg_trade = np.mean(returns) if returns else 0
    max_loss = min(returns) if returns else 0
    
    # Score against goals
    target = goal.get("target_return_30d", 0.20)
    max_dd = goal.get("max_drawdown", 0.05)
    min_sharpe = goal.get("min_sharpe", 1.2)
    failure = goal.get("failure_below", -0.04)
    
    # Composite score
    if total_return < failure:
        return -1.0
    elif total_return >= target:
        return 1.0
    else:
        return (total_return - failure) / (target - failure) * 2 - 1
