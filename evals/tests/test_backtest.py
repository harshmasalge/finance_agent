"""Backtest tests on synthetic prices (no network)."""
import numpy as np
import pandas as pd
import pytest

from evals import backtest as B


def _df(closes, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"Close": np.asarray(closes, dtype=float), "Volume": np.full(len(closes), 1000.0)}, index=idx)


def _walk(n, drift, seed, start=100.0):
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(drift + 0.01 * rng.standard_normal(n)))


def test_technicals_match_production_tool(monkeypatch):
    """Same formulas as backend/agent/tools/technical.py: feed the tool the same frame via a fake yfinance."""
    from backend.agent.tools import technical

    df = _df(_walk(260, 0.001, 1))

    class FakeTicker:
        def __init__(self, t):
            pass

        def history(self, period):
            return df

    monkeypatch.setattr(technical.yf, "Ticker", FakeTicker)
    assert B.technicals_from_history(df, "X.NS") == technical.get_technical_indicators("X.NS")


def test_window_has_no_lookahead():
    df = _df(_walk(400, 0.0, 2))
    t = df.index[300]
    w = B.window_at(df, t)
    assert w.index.max() == t and w.index.min() > t - pd.Timedelta(days=365)


def test_rebalance_dates_need_full_forward_window():
    cal = pd.bdate_range("2025-01-01", "2025-12-31")
    d = B.rebalance_dates(cal, n=12, horizon=30)
    assert all(x.day <= 3 for x in d)                  # first trading day of the month
    assert all(cal.get_loc(x) + 30 < len(cal) for x in d)
    assert d[-1] < pd.Timestamp("2025-11-15")          # Nov/Dec lack 30 forward days


def test_data_breaks():
    closes = list(_walk(50, 0.0, 3))
    closes[30:] = [c * 0.6 for c in closes[30:]]        # -40% one-day "demerger"
    df = _df(closes)
    assert B.data_breaks(df) == [df.index[30]]


@pytest.fixture(scope="module")
def synthetic():
    n = 700
    up, down = _walk(n, 0.002, 4), _walk(n, -0.002, 5)
    flat = _walk(n, 0.0, 6)
    broken = _walk(n, 0.0, 7)
    broken[600:] *= 0.5
    prices = {B.INDEX: _df(flat), "UP.NS": _df(up), "DOWN.NS": _df(down), "BRK.NS": _df(broken)}
    return B.run_backtest(prices, ["UP.NS", "DOWN.NS", "BRK.NS", "MISSING.NS"], horizon=30, n_rebalances=6, bootstrap=200)


def test_run_backtest_buckets(synthetic):
    r = synthetic
    assert len(r["rebalance_dates"]) == 6
    by = {b["verdict"]: b for b in r["buckets"]}
    obs = pd.DataFrame(r["observations"])
    assert set(obs[obs.ticker == "UP.NS"].verdict) <= {"BUY", "HOLD"}
    assert set(obs[obs.ticker == "DOWN.NS"].verdict) <= {"SELL", "HOLD"}
    assert by["ALL"]["count"] == len(obs) == sum(by[v]["count"] for v in ("BUY", "HOLD", "SELL"))
    assert by["HOLD"]["hit_rate"] is None and by["ALL"]["hit_rate"] is None
    if by["BUY"]["count"]:
        sub = obs[obs.verdict == "BUY"]
        assert by["BUY"]["hit_rate"] == pytest.approx((sub.excess > 0).mean(), abs=1e-4)
        assert by["BUY"]["mean_excess"] == pytest.approx(sub.excess.mean(), abs=1e-3)
    row = obs.iloc[0]
    assert row["excess"] == pytest.approx(row["ret"] - row["index_ret"], abs=1e-2)
    assert {"MISSING.NS"} == {s["ticker"] for s in r["skipped"]}
    assert r["excluded"] and all(e["ticker"] == "BRK.NS" for e in r["excluded"])
    assert set(r["factor_ic"]) <= {"trend", "momentum", "rsi", "returns"}


def test_future_prices_do_not_change_signals(synthetic):
    """Perturbing prices after the last rebalance's entry must not change any verdict (no look-ahead)."""
    n = 700
    up, down, flat = _walk(n, 0.002, 4), _walk(n, -0.002, 5), _walk(n, 0.0, 6)
    prices = {B.INDEX: _df(flat), "UP.NS": _df(up), "DOWN.NS": _df(down)}
    base = B.run_backtest(prices, ["UP.NS", "DOWN.NS"], horizon=30, n_rebalances=6, bootstrap=50)
    last = pd.Timestamp(base["rebalance_dates"][-1])
    shocked = {k: v.copy() for k, v in prices.items()}
    for k in ("UP.NS", "DOWN.NS"):
        shocked[k].loc[shocked[k].index > last, "Close"] *= 1.2  # below the data-break threshold
    after = B.run_backtest(shocked, ["UP.NS", "DOWN.NS"], horizon=30, n_rebalances=6, bootstrap=50)
    key = lambda r: [(o["date"], o["ticker"], o["score"], o["verdict"]) for o in r["observations"]]  # noqa: E731
    assert key(base) == key(after)
    # ...while the forward returns of the last rebalance DO see the shock
    last_ret = lambda r: [o["ret"] for o in r["observations"] if o["date"] == base["rebalance_dates"][-1]]  # noqa: E731
    assert last_ret(base) != last_ret(after)
