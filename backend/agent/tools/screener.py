import pandas as pd
import yfinance as yf

# Liquid large caps from the NIFTY 50 used as the idea universe (NSE symbols).
UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "BHARTIARTL.NS", "ITC.NS", "SBIN.NS",
    "LT.NS", "HINDUNILVR.NS", "KOTAKBANK.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "HCLTECH.NS", "TITAN.NS", "ASIANPAINT.NS", "ULTRACEMCO.NS", "NTPC.NS", "POWERGRID.NS", "TATASTEEL.NS",
    "WIPRO.NS", "TECHM.NS", "NESTLEIND.NS", "M&M.NS", "ONGC.NS", "COALINDIA.NS", "DRREDDY.NS", "CIPLA.NS",
]


def screen_nifty_stocks(exclude: list[str] | None = None, top_n: int = 5) -> dict:
    """
    Screens ~30 liquid NIFTY 50 stocks (NSE only) for new-position ideas using price momentum and trend:
    3-month return, price vs 50-day average, and RSI(14) not overbought (< 70).
    Pass tickers the user already holds in `exclude`. Returns the top_n ranked candidates with their metrics.
    """
    exclude = set(exclude or [])
    tickers = [t for t in UNIVERSE if t not in exclude]
    try:
        data = yf.download(tickers, period="6mo", interval="1d", progress=False, auto_adjust=True, group_by="ticker", threads=True)
    except Exception as e:
        return {"available": False, "message": f"Screener download failed: {e}"}

    rows = []
    for t in tickers:
        try:
            close = data[t]["Close"].dropna()
            if len(close) < 70:
                continue
            price = float(close.iloc[-1])
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            delta = close.diff()
            rs = delta.clip(lower=0).rolling(14).mean() / (-delta.clip(upper=0)).rolling(14).mean()
            rsi = float((100 - 100 / (1 + rs)).iloc[-1])
            ret3m = (price / float(close.iloc[-64]) - 1) * 100
            ret1m = (price / float(close.iloc[-22]) - 1) * 100
            rows.append({"ticker": t, "last_close": round(price, 2), "return_3m_pct": round(ret3m, 2),
                         "return_1m_pct": round(ret1m, 2), "pct_vs_ema50": round((price - ema50) / ema50 * 100, 2),
                         "rsi_14": round(rsi, 1)})
        except Exception:
            continue

    if not rows:
        return {"available": False, "message": "Screener returned no usable data."}
    df = pd.DataFrame(rows)
    eligible = df[(df["pct_vs_ema50"] > 0) & (df["rsi_14"] < 70)].copy()
    if eligible.empty:
        eligible = df.copy()
    eligible["score"] = eligible["return_3m_pct"].rank(pct=True) + eligible["pct_vs_ema50"].rank(pct=True)
    top = eligible.sort_values("score", ascending=False).head(top_n).drop(columns="score")
    return {
        "available": True,
        "universe_size": len(df),
        "method": "Above 50-day EMA, RSI < 70, ranked by 3-month return + distance above EMA50",
        "candidates": top.to_dict(orient="records"),
    }
