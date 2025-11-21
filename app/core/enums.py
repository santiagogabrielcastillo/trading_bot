from enum import Enum

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class PositionStatus(str, Enum):
    FLAT = "FLAT"           # No tenemos posición
    IN_POSITION = "IN_POSITION" # Tenemos posición abierta

class MarketState(str, Enum):
    """Market regime states for filtering trading signals."""
    TRENDING_UP = "TRENDING_UP"      # Strong uptrend
    TRENDING_DOWN = "TRENDING_DOWN"  # Strong downtrend
    RANGING = "RANGING"              # Sideways/ranging market