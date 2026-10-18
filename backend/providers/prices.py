"""One place to fetch and clean Yahoo Finance price history.

yfinance often returns a row for the current session whose Close is NaN (the session has not
settled yet). Code that reads `df["Close"].iloc[-1]` then treats NaN as the latest price, and
every indicator built on it is wrong (quality to-do A1). Every daily-history read in the app
goes through `clean_history` so that row never reaches a tool, a scorecard or the database.
"""
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

PRICE_COLUMNS = ("Open", "High", "Low", "Close")


def clean_history(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Drop rows without a usable close, plus duplicate timestamps; return oldest-first.

    A usable close is finite and > 0. Other price columns with non-finite values are set to NaN
    (not dropped), so a missing Open does not hide an otherwise valid close.
    """
    if df is None or df.empty or "Close" not in df.columns:
        return pd.DataFrame(columns=list(df.columns) if df is not None else list(PRICE_COLUMNS))
    out = df.copy()
    cols = [c for c in PRICE_COLUMNS + ("Volume",) if c in out.columns]
    out[cols] = out[cols].replace([np.inf, -np.inf], np.nan)
    out = out[out["Close"].notna() & (out["Close"] > 0)]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def get_history(ticker: str, period: str = "1y", interval: str = "1d", auto_adjust: bool = True) -> pd.DataFrame:
    """Price history for one ticker with unusable rows removed. Empty frame if Yahoo has nothing."""
    return clean_history(yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=auto_adjust))


def last_close(df: pd.DataFrame) -> Optional[float]:
    """Latest valid close of a frame (cleaned or not), or None."""
    clean = clean_history(df)
    return float(clean["Close"].iloc[-1]) if not clean.empty else None
