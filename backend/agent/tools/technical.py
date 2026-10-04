import pandas as pd
import yfinance as yf


def get_technical_indicators(ticker: str) -> dict:
    """
    Computes technical indicators for an NSE/BSE stock (e.g. 'INFY.NS') from 1 year of daily prices:
    last close, EMA 20/50/200 and distance from them, RSI(14), MACD histogram, volume ratio,
    1-month / 3-month returns and the 52-week high/low.
    """
    try:
        df = yf.Ticker(ticker).history(period="1y")
        if df.empty:
            return {"ticker": ticker, "available": False, "message": f"No price data found for {ticker}. Check the symbol."}
        close, volume = df["Close"], df["Volume"]
        price = float(close.iloc[-1])

        def ema(span):
            return float(close.ewm(span=span, adjust=False).mean().iloc[-1])

        e20, e50, e200 = ema(20), ema(50), ema(200)
        delta = close.diff()
        rs = delta.clip(lower=0).rolling(14).mean() / (-delta.clip(upper=0)).rolling(14).mean()
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_hist = float((macd - macd.ewm(span=9, adjust=False).mean()).iloc[-1])
        vol_avg = float(volume.rolling(20).mean().iloc[-2])

        def ret(days):
            return round((price / float(close.iloc[-days - 1]) - 1) * 100, 2) if len(close) > days else None

        return {
            "ticker": ticker,
            "available": True,
            "as_of": df.index[-1].strftime("%Y-%m-%d"),
            "last_close": round(price, 2),
            "ema_20": round(e20, 2), "ema_50": round(e50, 2), "ema_200": round(e200, 2),
            "pct_vs_ema20": round((price - e20) / e20 * 100, 2),
            "pct_vs_ema200": round((price - e200) / e200 * 100, 2),
            "rsi_14": round(rsi, 1) if not pd.isna(rsi) else None,
            "macd_histogram": round(macd_hist, 2),
            "volume_ratio_vs_20d": round(float(volume.iloc[-1]) / vol_avg, 2) if vol_avg else None,
            "return_1m_pct": ret(21),
            "return_3m_pct": ret(63),
            "high_52w": round(float(close.max()), 2),
            "low_52w": round(float(close.min()), 2),
        }
    except Exception as e:
        return {"ticker": ticker, "available": False, "message": f"Failed to compute technicals: {e}"}
