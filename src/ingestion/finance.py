"""
Financial Data Ingestion Module

Fetches market data for Texas-proxy equities using yfinance.
Supports the FIN <GO> command for market correlation analysis.

Texas Proxy Watchlist:
- VST (Vistra Corp) - Texas power generator, ERCOT exposure
- NRG (NRG Energy) - Integrated power company, Texas focus
- TXN (Texas Instruments) - Semiconductor, high water/power dependency

No API key required. Free and unlimited for daily data.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# Texas Proxy Watchlist - equities with physical Texas exposure
TEXAS_PROXY_WATCHLIST = {
    "VST": {
        "name": "Vistra Corp",
        "sector": "Energy",
        "exposure": "ERCOT power generation, 39GW capacity",
        "physical_link": "GRID",
        "sensitivity": "high",
    },
    "NRG": {
        "name": "NRG Energy",
        "sector": "Energy",
        "exposure": "Integrated power, retail electricity",
        "physical_link": "GRID",
        "sensitivity": "high",
    },
    "TXN": {
        "name": "Texas Instruments",
        "sector": "Technology",
        "exposure": "Semiconductor fabs, water/power intensive",
        "physical_link": "WATR,GRID",
        "sensitivity": "medium",
    },
}

# Movement thresholds for market reaction detection
MARKET_THRESHOLDS = {
    "minor_move": 1.0,      # 1% daily move
    "significant_move": 2.0, # 2% daily move - triggers correlation check
    "major_move": 5.0,       # 5% daily move - potential physical event
}


@dataclass
class StockQuote:
    """Represents a stock quote with market data."""
    symbol: str
    name: str
    price: float
    change: float
    change_percent: float
    volume: int
    market_cap: Optional[float]
    day_high: float
    day_low: float
    open_price: float
    prev_close: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "change": self.change,
            "change_percent": self.change_percent,
            "volume": self.volume,
            "market_cap": self.market_cap,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "open": self.open_price,
            "prev_close": self.prev_close,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class StockHistory:
    """Represents historical price data for sparkline rendering."""
    symbol: str
    prices: list[float]
    dates: list[str]
    period: str
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "prices": self.prices,
            "dates": self.dates,
            "period": self.period,
        }


# ─────────────────────────────────────────────────────────────
# Data Fetching Functions
# ─────────────────────────────────────────────────────────────

def fetch_watchlist_quotes(symbols: Optional[list[str]] = None) -> list[StockQuote]:
    """
    Fetch current quotes for Texas proxy watchlist.
    
    Args:
        symbols: Optional list of symbols. Defaults to full watchlist.
        
    Returns:
        List of StockQuote objects with current market data.
    """
    import yfinance as yf
    
    if symbols is None:
        symbols = list(TEXAS_PROXY_WATCHLIST.keys())
    
    quotes = []
    
    try:
        # Fetch all tickers at once for efficiency
        tickers = yf.Tickers(" ".join(symbols))
        
        for symbol in symbols:
            try:
                ticker = tickers.tickers.get(symbol)
                if not ticker:
                    continue
                
                info = ticker.info
                
                # Get latest price data
                price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or price
                change = price - prev_close if prev_close else 0
                change_pct = (change / prev_close * 100) if prev_close else 0
                
                # Get watchlist metadata
                watchlist_info = TEXAS_PROXY_WATCHLIST.get(symbol, {})
                
                quote = StockQuote(
                    symbol=symbol,
                    name=info.get("shortName") or watchlist_info.get("name", symbol),
                    price=price,
                    change=change,
                    change_percent=change_pct,
                    volume=info.get("volume") or info.get("regularMarketVolume") or 0,
                    market_cap=info.get("marketCap"),
                    day_high=info.get("dayHigh") or info.get("regularMarketDayHigh") or price,
                    day_low=info.get("dayLow") or info.get("regularMarketDayLow") or price,
                    open_price=info.get("open") or info.get("regularMarketOpen") or price,
                    prev_close=prev_close,
                    metadata={
                        "sector": watchlist_info.get("sector"),
                        "exposure": watchlist_info.get("exposure"),
                        "physical_link": watchlist_info.get("physical_link"),
                        "sensitivity": watchlist_info.get("sensitivity"),
                    },
                )
                quotes.append(quote)
                
                logger.debug(
                    "stock_quote_fetched",
                    symbol=symbol,
                    price=price,
                    change_pct=f"{change_pct:.2f}%",
                )
                
            except Exception as e:
                logger.warning("stock_quote_error", symbol=symbol, error=str(e))
                continue
        
        logger.info("watchlist_quotes_fetched", count=len(quotes))
        return quotes
        
    except Exception as e:
        logger.error("watchlist_fetch_error", error=str(e))
        return []


def fetch_stock_history(
    symbol: str,
    period: str = "5d",
    interval: str = "1h",
) -> Optional[StockHistory]:
    """
    Fetch historical price data for sparkline rendering.
    
    Args:
        symbol: Stock ticker symbol
        period: Time period (1d, 5d, 1mo, 3mo, etc.)
        interval: Data interval (1m, 5m, 15m, 1h, 1d)
        
    Returns:
        StockHistory object with price series
    """
    import yfinance as yf
    
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        
        if hist.empty:
            return None
        
        # Extract close prices and dates
        prices = hist["Close"].tolist()
        dates = [d.strftime("%Y-%m-%d %H:%M") for d in hist.index]
        
        return StockHistory(
            symbol=symbol,
            prices=prices,
            dates=dates,
            period=period,
        )
        
    except Exception as e:
        logger.error("stock_history_error", symbol=symbol, error=str(e))
        return None


def fetch_all_watchlist_history(period: str = "5d") -> dict[str, StockHistory]:
    """
    Fetch historical data for all watchlist symbols.
    
    Args:
        period: Time period for history
        
    Returns:
        Dict mapping symbol to StockHistory
    """
    import yfinance as yf
    
    symbols = list(TEXAS_PROXY_WATCHLIST.keys())
    histories = {}
    
    try:
        # Fetch all at once
        data = yf.download(
            symbols,
            period=period,
            interval="1h",
            group_by="ticker",
            progress=False,
        )
        
        for symbol in symbols:
            try:
                if len(symbols) > 1:
                    symbol_data = data[symbol]
                else:
                    symbol_data = data
                    
                if symbol_data.empty:
                    continue
                    
                prices = symbol_data["Close"].dropna().tolist()
                dates = [d.strftime("%Y-%m-%d %H:%M") for d in symbol_data.index]
                
                histories[symbol] = StockHistory(
                    symbol=symbol,
                    prices=prices,
                    dates=dates,
                    period=period,
                )
            except Exception as e:
                logger.warning("symbol_history_error", symbol=symbol, error=str(e))
                continue
        
        logger.info("watchlist_history_fetched", count=len(histories))
        return histories
        
    except Exception as e:
        logger.error("watchlist_history_fetch_error", error=str(e))
        return {}


# ─────────────────────────────────────────────────────────────
# Market Reaction Detection
# ─────────────────────────────────────────────────────────────

def detect_significant_moves(quotes: list[StockQuote]) -> list[dict[str, Any]]:
    """
    Detect significant price movements that may correlate with physical events.
    
    Args:
        quotes: List of current stock quotes
        
    Returns:
        List of significant move detections
    """
    moves = []
    
    for quote in quotes:
        abs_change = abs(quote.change_percent)
        
        if abs_change >= MARKET_THRESHOLDS["major_move"]:
            move_type = "MAJOR"
            severity = 3
        elif abs_change >= MARKET_THRESHOLDS["significant_move"]:
            move_type = "SIGNIFICANT"
            severity = 2
        elif abs_change >= MARKET_THRESHOLDS["minor_move"]:
            move_type = "MINOR"
            severity = 1
        else:
            continue
        
        direction = "UP" if quote.change_percent > 0 else "DOWN"
        
        moves.append({
            "symbol": quote.symbol,
            "name": quote.name,
            "move_type": move_type,
            "direction": direction,
            "change_percent": quote.change_percent,
            "severity": severity,
            "physical_link": quote.metadata.get("physical_link"),
            "timestamp": quote.timestamp.isoformat(),
        })
        
        logger.info(
            "market_move_detected",
            symbol=quote.symbol,
            move_type=move_type,
            direction=direction,
            change_pct=f"{quote.change_percent:.2f}%",
        )
    
    return moves


def get_market_summary() -> dict[str, Any]:
    """
    Get overall market summary for Texas proxy watchlist.
    
    Returns:
        Dict with market summary data
    """
    quotes = fetch_watchlist_quotes()
    
    if not quotes:
        return {
            "status": "unavailable",
            "message": "Unable to fetch market data",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    # Calculate aggregate metrics
    total_market_cap = sum(q.market_cap or 0 for q in quotes)
    avg_change = sum(q.change_percent for q in quotes) / len(quotes)
    
    # Detect significant moves
    significant_moves = detect_significant_moves(quotes)
    
    return {
        "status": "active",
        "quotes": [q.to_dict() for q in quotes],
        "aggregate": {
            "total_market_cap": total_market_cap,
            "avg_change_percent": avg_change,
            "symbols_up": sum(1 for q in quotes if q.change_percent > 0),
            "symbols_down": sum(1 for q in quotes if q.change_percent < 0),
        },
        "significant_moves": significant_moves,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# Celery Task Integration
# ─────────────────────────────────────────────────────────────

def fetch_and_cache_market_data() -> dict[str, Any]:
    """
    Fetch market data and prepare for caching/analysis.
    Called by Celery scheduled task.
    
    Returns:
        Dict with fetch summary
    """
    try:
        # Get quotes
        quotes = fetch_watchlist_quotes()
        
        # Get historical data for sparklines
        histories = fetch_all_watchlist_history(period="5d")
        
        # Detect moves
        moves = detect_significant_moves(quotes)
        
        return {
            "status": "success",
            "quotes_fetched": len(quotes),
            "histories_fetched": len(histories),
            "significant_moves": len(moves),
            "moves": moves,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
    except Exception as e:
        logger.error("market_data_fetch_error", error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
