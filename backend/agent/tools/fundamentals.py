import yfinance as yf


def get_fundamentals(ticker: str) -> dict:
    """
    Fetches fundamentals for an NSE/BSE stock (e.g. 'HDFCBANK.NS'): company name, sector, market cap,
    trailing/forward P/E, P/B, EPS, ROE, profit margin, revenue & earnings growth, debt-to-equity, dividend yield.
    Missing fields are returned as null - do not estimate them.
    """
    try:
        info = yf.Ticker(ticker).info
        if not info or not (info.get("shortName") or info.get("longName")):
            return {"ticker": ticker, "available": False, "message": f"No fundamentals found for {ticker}."}

        def pct(key):
            v = info.get(key)
            return round(v * 100, 2) if isinstance(v, (int, float)) else None

        def num(key, nd=2):
            v = info.get(key)
            return round(v, nd) if isinstance(v, (int, float)) else None

        mcap = info.get("marketCap")
        return {
            "ticker": ticker,
            "available": True,
            "company": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap_cr": round(mcap / 1e7, 0) if mcap else None,
            "pe_trailing": num("trailingPE"),
            "pe_forward": num("forwardPE"),
            "price_to_book": num("priceToBook"),
            "eps_trailing": num("trailingEps"),
            "roe_pct": pct("returnOnEquity"),
            "profit_margin_pct": pct("profitMargins"),
            "revenue_growth_pct": pct("revenueGrowth"),
            "earnings_growth_pct": pct("earningsGrowth"),
            "debt_to_equity": num("debtToEquity"),
            "dividend_yield_pct": num("dividendYield"),
        }
    except Exception as e:
        return {"ticker": ticker, "available": False, "message": f"Failed to fetch fundamentals: {e}"}
