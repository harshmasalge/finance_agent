from typing import Dict, Any, Optional
import structlog
import yfinance as yf

logger = structlog.get_logger(__name__)

class MarketDataProvider:
    """
    Abstraction layer for market data. Currently wraps yfinance and nsetools.
    Can be upgraded to Angel One SmartAPI in the future without changing the caller code.
    """
    
    def __init__(self):
        # Future init for API keys or client connections
        pass
        
    def get_latest_price(self, ticker: str) -> Optional[float]:
        """
        Fetches the latest available price for a given ticker.
        """
        try:
            stock = yf.Ticker(ticker)
            
            # Attempt to use the real-time quote API first
            if hasattr(stock, 'fast_info') and 'lastPrice' in stock.fast_info:
                price = float(stock.fast_info['lastPrice'])
                if price > 0:
                    return price

            # Fallback to 1m intraday data
            data = stock.history(period="1d", interval="1m")
            if not data.empty:
                return float(data['Close'].iloc[-1])
                
            return None
        except Exception as e:
            logger.error("Failed to fetch latest price", ticker=ticker, error=str(e))
            return None
            
    def get_historical_data(self, ticker: str, period: str = "1mo", interval: str = "1d") -> Any:
        """
        Fetches historical OHLCV data.
        Returns a pandas DataFrame (returned directly from yfinance).
        """
        try:
            stock = yf.Ticker(ticker)
            return stock.history(period=period, interval=interval)
        except Exception as e:
            logger.error("Failed to fetch historical data", ticker=ticker, error=str(e))
            return None
