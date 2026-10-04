"""
Point-in-time backtest of the rule-based signal scorecard on PRICE-BASED factors only.

For each monthly rebalance date t over the last 12 months and each current NIFTY 50 constituent:
  1. take the 1 calendar year of daily prices ending at t (what `get_technical_indicators` sees live: period="1y"),
  2. compute the same indicators with the same formulas as `backend/agent/tools/technical.py`,
  3. score them with the production `backend.agent.scoring.score_ticker` -> BUY / HOLD / SELL,
  4. measure the forward return from the close at t to the close 30 trading days later, minus NIFTY 50 (^NSEI).

Factors used: trend (vs EMA50/200), momentum (vs EMA20 + MACD histogram), RSI(14), 3-month return.
Excluded: fundamentals, news sentiment, Prophet and XGBoost - no point-in-time history is available for
them (and the models would need walk-forward retraining), so this tests the price half of the scorecard only.

    python -m evals.backtest            # uses the cached download if present
    python -m evals.backtest --refresh  # re-download constituents and prices

Writes evals/results/backtest_latest.json. Price data is cached in evals/cache/ (git-ignored).
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from backend.agent.scoring import score_ticker

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.getenv("EVALS_CACHE_DIR", ROOT / "evals" / "cache"))
RESULTS_DIR = Path(os.getenv("EVALS_RESULTS_DIR", ROOT / "evals" / "results"))
CONSTITUENTS_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
SNAPSHOT = ROOT / "evals" / "nifty50_constituents.csv"  # committed copy of the list used
INDEX = "^NSEI"
HORIZON = 30          # trading days held after each rebalance
N_REBALANCES = 12     # monthly rebalances
MIN_HISTORY = 200     # trading days of history needed before a date to score it (EMA200 warm-up)
LOOKBACK_DAYS = 365   # calendar window fed to the indicators (= yfinance period="1y")
VERDICTS = ("BUY", "HOLD", "SELL")
MAX_DAILY_MOVE = 0.25  # a one-day close-to-close move beyond +/-25% in a NIFTY 50 stock is treated as a data break


# --------------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------------


def load_constituents(refresh: bool = False) -> pd.DataFrame:
    """Current NIFTY 50 list (Company Name, Industry, Symbol, ...). Downloads from niftyindices.com, falls back to the
    committed snapshot."""
    if refresh or not SNAPSHOT.exists():
        import requests

        r = requests.get(CONSTITUENTS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if len(df) < 45 or "Symbol" not in df:
            raise RuntimeError(f"unexpected constituents file ({len(df)} rows)")
        SNAPSHOT.write_text(r.text.replace("\r\n", "\n"), encoding="utf-8")
    return pd.read_csv(SNAPSHOT)


def yahoo_symbol(nse_symbol: str) -> str:
    """NSE symbol -> Yahoo Finance ticker."""
    return f"{nse_symbol.strip()}.NS"


def load_prices(tickers: Sequence[str], start: date, end: date, refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """One batched yfinance download for all tickers + the index, cached to evals/cache/prices.pkl.
    Returns ticker -> DataFrame[Close, Volume] (auto-adjusted, NaN rows dropped)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "prices.pkl"
    meta_path = CACHE / "prices.meta.json"
    want = sorted(set(tickers) | {INDEX})
    if not refresh and path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if set(want) <= set(meta["tickers"]) and meta["start"] <= start.isoformat() and meta["end"] >= end.isoformat():
            raw = pd.read_pickle(path)
            return _split(raw, want)
    import yfinance as yf

    raw = yf.download(want, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), interval="1d",
                      auto_adjust=True, group_by="ticker", progress=False, threads=True)
    raw.to_pickle(path)
    meta_path.write_text(json.dumps({"tickers": want, "start": start.isoformat(), "end": end.isoformat(),
                                     "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    return _split(raw, want)


def _split(raw: pd.DataFrame, tickers: Sequence[str]) -> Dict[str, pd.DataFrame]:
    out = {}
    for t in tickers:
        try:
            df = raw[t][["Close", "Volume"]].dropna(subset=["Close"])
        except KeyError:
            continue
        if not df.empty:
            df.index = pd.to_datetime(df.index).tz_localize(None)
            out[t] = df
    return out


# --------------------------------------------------------------------------------------------
# Indicators (same formulas as backend/agent/tools/technical.py, applied to a historical window)
# --------------------------------------------------------------------------------------------


def technicals_from_history(df: pd.DataFrame, ticker: str) -> dict:
    """Replicates `get_technical_indicators` on a given price window (DataFrame with Close, Volume)."""
    if df.empty:
        return {"ticker": ticker, "available": False, "message": "no data"}
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
    vol_avg = float(volume.rolling(20).mean().iloc[-2]) if len(volume) > 20 else float("nan")

    def ret(days):
        return round((price / float(close.iloc[-days - 1]) - 1) * 100, 2) if len(close) > days else None

    return {
        "ticker": ticker, "available": True, "as_of": df.index[-1].strftime("%Y-%m-%d"),
        "last_close": round(price, 2),
        "ema_20": round(e20, 2), "ema_50": round(e50, 2), "ema_200": round(e200, 2),
        "pct_vs_ema20": round((price - e20) / e20 * 100, 2),
        "pct_vs_ema200": round((price - e200) / e200 * 100, 2),
        "rsi_14": round(rsi, 1) if not pd.isna(rsi) else None,
        "macd_histogram": round(macd_hist, 2),
        "volume_ratio_vs_20d": round(float(volume.iloc[-1]) / vol_avg, 2) if vol_avg and not math.isnan(vol_avg) else None,
        "return_1m_pct": ret(21), "return_3m_pct": ret(63),
        "high_52w": round(float(close.max()), 2), "low_52w": round(float(close.min()), 2),
    }


def data_breaks(df: pd.DataFrame, threshold: float = MAX_DAILY_MOVE) -> List[pd.Timestamp]:
    """Days with a one-day move beyond +/-threshold. In NIFTY 50 large caps these are almost always corporate actions
    the free price feed did not adjust (e.g. the Tata Motors demerger, bonus issues), not real returns."""
    r = df["Close"].pct_change().abs()
    return list(r[r > threshold].index)


def window_at(df: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """Prices in the 1-calendar-year window ending at t (inclusive) - no data after t is visible."""
    return df[(df.index > t - pd.Timedelta(days=LOOKBACK_DAYS)) & (df.index <= t)]


# --------------------------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------------------------


def rebalance_dates(calendar: pd.DatetimeIndex, n: int = N_REBALANCES, horizon: int = HORIZON) -> List[pd.Timestamp]:
    """First trading day of each month, keeping the latest `n` whose forward window of `horizon` days is complete."""
    cal = pd.DatetimeIndex(sorted(calendar))
    firsts = pd.Series(cal, index=cal).groupby([cal.year, cal.month]).first().tolist()
    complete = [d for d in firsts if cal.get_loc(d) + horizon < len(cal)]
    return complete[-n:]


def _stats(x: Sequence[float]) -> dict:
    a = np.asarray(x, dtype=float)
    if a.size == 0:
        return {"n": 0, "mean": None, "median": None, "std": None, "pct_positive": None}
    return {"n": int(a.size), "mean": round(float(a.mean()), 3), "median": round(float(np.median(a)), 3),
            "std": round(float(a.std(ddof=1)), 3) if a.size > 1 else None, "pct_positive": round(float((a > 0).mean()), 4)}


def _spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    if len(x) < 5:
        return None
    rx, ry = pd.Series(x).rank(), pd.Series(y).rank()
    c = float(np.corrcoef(rx, ry)[0, 1])
    return None if math.isnan(c) else round(c, 4)


def run_backtest(prices: Dict[str, pd.DataFrame], tickers: Sequence[str], horizon: int = HORIZON,
                 n_rebalances: int = N_REBALANCES, bootstrap: int = 2000, seed: int = 7) -> dict:
    """Score every ticker at every rebalance date and measure forward excess returns. Pure given `prices`."""
    idx = prices[INDEX]["Close"]
    cal = idx.index
    dates = rebalance_dates(cal, n_rebalances, horizon)
    obs, skipped, excluded = [], {}, []
    breaks = {tk: data_breaks(prices[tk]) for tk in tickers if tk in prices}
    for t in dates:
        exit_t = cal[cal.get_loc(t) + horizon]
        idx_ret = (float(idx.loc[exit_t]) / float(idx.loc[t]) - 1) * 100
        for tk in tickers:
            df = prices.get(tk)
            if df is None:
                skipped.setdefault(tk, "no price data")
                continue
            hist = df[df.index <= t]
            if len(hist) < MIN_HISTORY or t not in df.index or exit_t not in df.index:
                skipped.setdefault(tk, f"insufficient history at {t.date()}" if len(hist) < MIN_HISTORY else f"no price on {t.date()} or {exit_t.date()}")
                continue
            brk = [b for b in breaks.get(tk, []) if t - pd.Timedelta(days=LOOKBACK_DAYS) < b <= exit_t]
            if brk:
                excluded.append({"ticker": tk, "date": t.date().isoformat(),
                                 "reason": f"suspected unadjusted corporate action: {float(df['Close'].pct_change().loc[brk[0]]):+.0%} on {brk[0].date()}"})
                continue
            tech = technicals_from_history(window_at(df, t), tk)
            card = score_ticker(tk, {"get_technical_indicators": tech}, {"get_technical_indicators": "R1"})
            ret = (float(df["Close"].loc[exit_t]) / float(df["Close"].loc[t]) - 1) * 100
            obs.append({"date": t.date().isoformat(), "exit": exit_t.date().isoformat(), "ticker": tk,
                        "score": card["score"], "verdict": card["verdict"], "ret": round(ret, 3),
                        "index_ret": round(idx_ret, 3), "excess": round(ret - idx_ret, 3),
                        "factors": {f["name"]: f["score"] for f in card["factors"]}})

    o = pd.DataFrame(obs)
    buckets = []
    for v in VERDICTS:
        sub = o[o.verdict == v] if len(o) else o
        st = _stats(sub["excess"]) if len(sub) else _stats([])
        hit = None
        if len(sub) and v == "BUY":
            hit = round(float((sub.excess > 0).mean()), 4)
        elif len(sub) and v == "SELL":
            hit = round(float((sub.excess < 0).mean()), 4)
        buckets.append({"verdict": v, "count": st["n"], "hit_rate": hit, "pct_outperform": st["pct_positive"],
                        "mean_excess": st["mean"], "median_excess": st["median"], "std_excess": st["std"],
                        "mean_return": round(float(sub["ret"].mean()), 3) if len(sub) else None})
    st = _stats(o["excess"]) if len(o) else _stats([])
    buckets.append({"verdict": "ALL", "count": st["n"], "hit_rate": None, "pct_outperform": st["pct_positive"],
                    "mean_excess": st["mean"], "median_excess": st["median"], "std_excess": st["std"],
                    "mean_return": round(float(o["ret"].mean()), 3) if len(o) else None})

    per_date, ics = [], []
    for d, g in (o.groupby("date") if len(o) else []):
        row = {"date": d, "exit": g["exit"].iloc[0], "index_return": g["index_ret"].iloc[0], "n": len(g)}
        for v in VERDICTS:
            gv = g[g.verdict == v]
            row[f"n_{v.lower()}"] = int(len(gv))
            row[f"mean_excess_{v.lower()}"] = round(float(gv["excess"].mean()), 3) if len(gv) else None
        row["mean_excess_all"] = round(float(g["excess"].mean()), 3)
        row["ic"] = _spearman(g["score"].tolist(), g["excess"].tolist())
        if row["ic"] is not None:
            ics.append(row["ic"])
        per_date.append(row)

    # Which price factors carry signal? Mean per-date rank IC of each factor score vs forward excess return.
    factor_ic = {}
    if len(o):
        fac = pd.DataFrame(o["factors"].tolist(), index=o.index)
        for name in fac.columns:
            vals = []
            for _, g in o.groupby("date"):
                ic = _spearman(fac.loc[g.index, name].tolist(), g["excess"].tolist())
                if ic is not None:
                    vals.append(ic)
            factor_ic[name] = {"mean_ic": round(float(np.mean(vals)), 4) if vals else None, "n_dates": len(vals),
                               "positive_dates": sum(1 for v in vals if v > 0)}

    # BUY-minus-SELL spread with a bootstrap over rebalance dates (dates, not stocks, are the independent-ish unit)
    spread = None
    if len(o) and (o.verdict == "BUY").any() and (o.verdict == "SELL").any():
        rng = np.random.default_rng(seed)
        groups = {d: g for d, g in o.groupby("date")}
        keys = list(groups)
        point = float(o[o.verdict == "BUY"].excess.mean() - o[o.verdict == "SELL"].excess.mean())
        draws = []
        for _ in range(bootstrap):
            sample = pd.concat([groups[keys[i]] for i in rng.integers(0, len(keys), len(keys))])
            b, s = sample[sample.verdict == "BUY"].excess, sample[sample.verdict == "SELL"].excess
            if len(b) and len(s):
                draws.append(float(b.mean() - s.mean()))
        both = [r for r in per_date if r["mean_excess_buy"] is not None and r["mean_excess_sell"] is not None]
        spread = {"buy_minus_sell_mean_excess": round(point, 3),
                  "ci95": [round(float(np.percentile(draws, 2.5)), 3), round(float(np.percentile(draws, 97.5)), 3)] if draws else None,
                  "dates_with_both": len(both),
                  "dates_buy_beats_sell": sum(1 for r in both if r["mean_excess_buy"] > r["mean_excess_sell"])}

    return {
        "rebalance_dates": [d.date().isoformat() for d in dates],
        "data_end": cal[-1].date().isoformat(),
        "n_observations": len(obs), "n_tickers_scored": int(o["ticker"].nunique()) if len(o) else 0,
        "buckets": buckets, "per_date": per_date, "spread": spread,
        "rank_ic": {"mean": round(float(np.mean(ics)), 4) if ics else None, "n_dates": len(ics),
                    "positive_dates": sum(1 for x in ics if x > 0)},
        "factor_ic": factor_ic,
        "skipped": [{"ticker": k, "reason": v} for k, v in sorted(skipped.items())],
        "excluded": excluded,
        "observations": obs,
    }


CAVEATS = [
    "Price-based factors only (trend, momentum, RSI, 3-month return). Fundamentals, news sentiment, Prophet and XGBoost "
    "are excluded because no point-in-time history exists for them; the live scorecard blends all of them, so this does "
    "not validate the full verdict.",
    "Survivorship bias: the universe is TODAY's NIFTY 50 list applied to the past 12 months. Stocks that left the index "
    "(often after underperforming) are missing and recent entrants are included, which flatters long signals.",
    "Overlapping windows: 30-trading-day holds (~6 weeks) from monthly rebalances overlap, and stocks in the same month "
    "share market moves, so observations are not independent. The confidence interval resamples whole rebalance dates.",
    "One 12-month window is a single market regime; results are not evidence of a durable edge.",
    "Close-to-close returns on auto-adjusted Yahoo Finance prices; no transaction costs, slippage or dividends beyond the adjustment.",
    "Data breaks: observations whose lookback or holding window contains a one-day move beyond +/-25% are excluded as "
    "suspected unadjusted corporate actions (the Tata Motors demerger in Oct 2025 shows as -40% in TMPV.NS; TRENT.NS shows "
    "-33% on 2026-01-01 on normal volume). See `excluded`.",
    "Thresholds (+/-15) are the production thresholds, applied to the score normalised over the price factors only.",
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-download the constituent list and prices")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    ap.add_argument("--rebalances", type=int, default=N_REBALANCES)
    ap.add_argument("--out", default=str(RESULTS_DIR))
    a = ap.parse_args(argv)

    cons = load_constituents(a.refresh)
    tickers = [yahoo_symbol(s) for s in cons["Symbol"]]
    end = date.today()
    start = end - timedelta(days=int((a.rebalances + 3) * 31 + LOOKBACK_DAYS + 30))
    prices = load_prices(tickers, start, end, a.refresh)
    res = run_backtest(prices, tickers, a.horizon, a.rebalances)
    meta = json.loads((CACHE / "prices.meta.json").read_text()) if (CACHE / "prices.meta.json").exists() else {}
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"horizon_trading_days": a.horizon, "rebalances": a.rebalances, "rebalance_rule": "first trading day of each month",
                   "lookback_calendar_days": LOOKBACK_DAYS, "min_history_days": MIN_HISTORY, "benchmark": INDEX,
                   "factors": ["trend", "momentum", "rsi", "returns"], "thresholds": {"buy": 15, "sell": -15},
                   "hit_rate_definition": "BUY: excess return > 0; SELL: excess return < 0; HOLD: not defined (see pct_outperform)"},
        "universe": {"name": "NIFTY 50 (current constituents)", "source": CONSTITUENTS_URL, "n": len(tickers),
                     "prices_downloaded_at": meta.get("downloaded_at"), "survivorship_bias": True},
        **res,
        "caveats": CAVEATS,
    }
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "backtest_latest.json"
    p.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(f"rebalances: {res['rebalance_dates'][0]} .. {res['rebalance_dates'][-1]} · obs {res['n_observations']} · tickers {res['n_tickers_scored']}")
    print(f"{'bucket':6} {'n':>5} {'hit':>7} {'%>idx':>7} {'mean':>8} {'median':>8}")
    for b in res["buckets"]:
        f = lambda v, pct=False: "n/a" if v is None else (f"{v:.1%}" if pct else f"{v:+.2f}")  # noqa: E731
        print(f"{b['verdict']:6} {b['count']:>5} {f(b['hit_rate'], True):>7} {f(b['pct_outperform'], True):>7} {f(b['mean_excess']):>8} {f(b['median_excess']):>8}")
    print("spread:", res["spread"], "· rank IC:", res["rank_ic"])
    print("factor IC:", res["factor_ic"])
    print("skipped:", res["skipped"])
    print("excluded:", len(res["excluded"]), sorted({e["ticker"] for e in res["excluded"]}))
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
