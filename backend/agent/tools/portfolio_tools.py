from backend.db.database import SessionLocal, redis_client
from backend.db.models import Portfolio, User
from backend.providers.market_data_provider import MarketDataProvider

_market = MarketDataProvider()


def _live_price(ticker: str, fallback: float) -> float:
    try:
        cached = redis_client.get(f"live_price:{ticker}")
        if cached:
            return float(cached)
    except Exception:
        pass
    price = _market.get_latest_price(ticker)
    return float(price) if price else fallback


def get_portfolio_position(user_id: int, ticker: str) -> dict:
    """
    Returns the user's holding in one NSE/BSE stock: quantity, average cost, current price,
    market value, unrealised P&L and any stop-loss / target percentages set.
    """
    db = SessionLocal()
    try:
        h = db.query(Portfolio).filter(Portfolio.user_id == int(user_id), Portfolio.ticker == ticker, Portfolio.quantity > 0).first()
        if not h:
            return {"ticker": ticker, "held": False, "message": f"The user does not hold {ticker}."}
        price = _live_price(h.ticker, h.avg_cost)
        cost = h.quantity * h.avg_cost
        value = h.quantity * price
        return {
            "ticker": ticker,
            "held": True,
            "quantity": h.quantity,
            "avg_cost": round(h.avg_cost, 2),
            "current_price": round(price, 2),
            "market_value": round(value, 2),
            "unrealised_pnl": round(value - cost, 2),
            "unrealised_pnl_pct": round((value - cost) / cost * 100, 2) if cost else 0.0,
            "stop_loss_pct": h.sl_pct,
            "target_pct": h.tg_pct,
        }
    finally:
        db.close()


def get_portfolio_risk_summary(user_id: int) -> dict:
    """
    Summarises the user's whole paper portfolio at current market prices: cash, invested value,
    market value, total unrealised P&L, per-holding weights and P&L, the largest position,
    and concentration flags (any holding above 30% of the portfolio).
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        holdings = db.query(Portfolio).filter(Portfolio.user_id == int(user_id), Portfolio.quantity > 0).all()
        cash = float(user.virtual_balance) if user else 0.0
        if not holdings:
            return {"empty": True, "cash": round(cash, 2), "message": "The portfolio has no holdings."}

        rows, total_value, total_cost = [], 0.0, 0.0
        for h in holdings:
            price = _live_price(h.ticker, h.avg_cost)
            value, cost = h.quantity * price, h.quantity * h.avg_cost
            total_value += value
            total_cost += cost
            rows.append({"ticker": h.ticker, "quantity": h.quantity, "avg_cost": round(h.avg_cost, 2),
                         "current_price": round(price, 2), "market_value": round(value, 2),
                         "unrealised_pnl_pct": round((value - cost) / cost * 100, 2) if cost else 0.0})
        for r in rows:
            r["weight_pct"] = round(r["market_value"] / total_value * 100, 2) if total_value else 0.0
        rows.sort(key=lambda r: r["weight_pct"], reverse=True)

        return {
            "empty": False,
            "cash": round(cash, 2),
            "invested_cost": round(total_cost, 2),
            "market_value": round(total_value, 2),
            "unrealised_pnl": round(total_value - total_cost, 2),
            "unrealised_pnl_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0.0,
            "cash_pct_of_account": round(cash / (cash + total_value) * 100, 2) if (cash + total_value) else 0.0,
            "n_holdings": len(rows),
            "holdings": rows,
            "largest_position": rows[0]["ticker"],
            "concentration_flags": [r["ticker"] for r in rows if r["weight_pct"] > 30],
        }
    finally:
        db.close()
