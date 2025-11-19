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