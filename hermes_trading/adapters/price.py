"""
Price data adapter for Coinbase. Pulls 1h OHLCV candles for BTC/USDT.
Falls back to free public data (CoinGecko for price history).
"""
import httpx
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def fetch(asset: str = "BTC/USDT", timeframe: str = "1h") -> dict:
    """
    Fetch price data from Coinbase.
    
    Args:
        asset: Trading pair (e.g., 'BTC/USDT')
        timeframe: Candle size (e.g., '1h')
    
    Returns:
        dict with OHLCV data
    """
    try:
        # For now, return mock data (paper mode)
        # In live mode, this would call Coinbase REST API
        return {
            "asset": asset,
            "timeframe": timeframe,
            "timestamp": None,
            "ohlcv": []
        }
    except Exception as e:
        logger.error(f"Price fetch failed: {e}")
        return {}
