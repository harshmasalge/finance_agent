import numpy as np
import pandas as pd
import xgboost as xgb
import yfinance as yf
from prophet import Prophet


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    return 100 - (100 / (1 + gain / loss))


def extract_prophet_features(ticker: str) -> dict:
    """
    Fits a Prophet trend model on 2 years of daily closes for an NSE/BSE stock (e.g. 'TCS.NS').
    Returns the trend direction (UPTREND / DOWNTREND / SIDEWAYS), the fitted trend price,
    how far the last close sits from that trend, and the daily trend slope.
    """
    try:
        df = yf.Ticker(ticker).history(period="2y")
        if len(df) < 100:
            return {"ticker": ticker, "available": False, "message": "Not enough price history for Prophet."}
        pdf = df.reset_index()[["Date", "Close"]].rename(columns={"Date": "ds", "Close": "y"})
        pdf["ds"] = pdf["ds"].dt.tz_localize(None)
        last_price = float(pdf.iloc[-1]["y"])

        m = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=len(pdf) >= 500)
        m.fit(pdf.iloc[:-1])
        fc = m.predict(m.make_future_dataframe(periods=1))
        trend, prev = float(fc.iloc[-1]["trend"]), float(fc.iloc[-2]["trend"])
        slope_pct = (trend - prev) / prev * 100 if prev else 0.0
        direction = "UPTREND" if slope_pct > 0.03 else "DOWNTREND" if slope_pct < -0.03 else "SIDEWAYS"
        return {
            "ticker": ticker,
            "available": True,
            "trend_direction": direction,
            "trend_price": round(trend, 2),
            "last_close": round(last_price, 2),
            "pct_above_trend": round((last_price - trend) / trend * 100, 2),
            "trend_slope_pct_per_day": round(slope_pct, 4),
        }
    except Exception as e:
        return {"ticker": ticker, "available": False, "message": f"Prophet failed: {e}"}


def get_xgboost_signal(ticker: str) -> dict:
    """
    Trains a small XGBoost classifier on 2 years of an NSE/BSE stock's own history and predicts
    whether the next 5 trading days are likely to move >2% up (BUY), >2% down (SELL) or neither (HOLD).
    Also reports the model's out-of-sample accuracy so the signal can be weighted honestly.
    """
    try:
        df = yf.Ticker(ticker).history(period="2y")
        if len(df) < 150:
            return {"ticker": ticker, "available": False, "message": "Not enough price history for XGBoost."}
        close = df["Close"]
        feats = pd.DataFrame(index=df.index)
        feats["rsi"] = _rsi(close)
        ema20 = close.ewm(span=20, adjust=False).mean()
        feats["pct_vs_ema20"] = (close - ema20) / ema20 * 100
        feats["ret_5d"] = close.pct_change(5) * 100
        feats["vol_ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()

        fwd = close.shift(-5) / close - 1
        target = np.where(fwd > 0.02, 1, np.where(fwd < -0.02, 2, 0))  # 1=BUY 2=SELL 0=HOLD
        data = feats.assign(target=target, fwd=fwd).dropna()
        latest = feats.dropna().iloc[[-1]]
        if len(data) < 100:
            return {"ticker": ticker, "available": False, "message": "Not enough rows after feature engineering."}

        split = int(len(data) * 0.8)
        cols = ["rsi", "pct_vs_ema20", "ret_5d", "vol_ratio"]
        model = xgb.XGBClassifier(objective="multi:softprob", num_class=3, max_depth=3, n_estimators=80, random_state=42)
        model.fit(data[cols].iloc[:split], data["target"].iloc[:split])
        holdout_acc = float((model.predict(data[cols].iloc[split:]) == data["target"].iloc[split:]).mean())

        model.fit(data[cols], data["target"])
        probs = model.predict_proba(latest[cols])[0]
        labels = ["HOLD", "BUY", "SELL"]
        return {
            "ticker": ticker,
            "available": True,
            "signal": labels[int(np.argmax(probs))],
            "probabilities": {"BUY": round(float(probs[1]), 2), "SELL": round(float(probs[2]), 2), "HOLD": round(float(probs[0]), 2)},
            "holdout_accuracy": round(holdout_acc, 2),
            "note": "Trained on this stock's own 2y history; treat as a weak signal if holdout_accuracy is below ~0.5.",
        }
    except Exception as e:
        return {"ticker": ticker, "available": False, "message": f"XGBoost failed: {e}"}
