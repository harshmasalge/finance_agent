"""Company names and aliases for NSE/BSE tickers.

News never says "SBIN.NS" or "TATASTEEL" - it says "SBI", "State Bank of India", "Tata Steel".
Both the news search query and the "is this article about the stock?" check use these names.
"""
import re
from functools import lru_cache
from typing import List

# Symbol (without .NS/.BO) -> names used in news. First entry is the canonical company name.
# Short aliases (TCS, SBI, RIL...) are matched as whole words only.
ALIASES = {
    "RELIANCE": ["Reliance Industries", "RIL"],
    "TCS": ["Tata Consultancy Services", "TCS"],
    "INFY": ["Infosys"],
    "WIPRO": ["Wipro"],
    "HCLTECH": ["HCLTech", "HCL Technologies", "HCL Tech"],
    "TECHM": ["Tech Mahindra"],
    "LTIM": ["LTIMindtree"],
    "HDFCBANK": ["HDFC Bank"],
    "ICICIBANK": ["ICICI Bank"],
    "SBIN": ["State Bank of India", "SBI"],
    "KOTAKBANK": ["Kotak Mahindra Bank", "Kotak Bank"],
    "AXISBANK": ["Axis Bank"],
    "INDUSINDBK": ["IndusInd Bank"],
    "BAJFINANCE": ["Bajaj Finance"],
    "BAJAJFINSV": ["Bajaj Finserv"],
    "HDFCLIFE": ["HDFC Life"],
    "SBILIFE": ["SBI Life"],
    "TATASTEEL": ["Tata Steel"],
    "JSWSTEEL": ["JSW Steel"],
    "HINDALCO": ["Hindalco"],
    "COALINDIA": ["Coal India"],
    "ONGC": ["ONGC", "Oil and Natural Gas Corporation"],
    "NTPC": ["NTPC"],
    "POWERGRID": ["Power Grid"],
    "BPCL": ["BPCL", "Bharat Petroleum"],
    "TATAMOTORS": ["Tata Motors"],
    "MARUTI": ["Maruti Suzuki", "Maruti"],
    "M&M": ["Mahindra & Mahindra", "Mahindra and Mahindra", "M&M"],
    "BAJAJ-AUTO": ["Bajaj Auto"],
    "EICHERMOT": ["Eicher Motors", "Royal Enfield"],
    "HEROMOTOCO": ["Hero MotoCorp"],
    "HINDUNILVR": ["Hindustan Unilever", "HUL"],
    "ITC": ["ITC"],
    "NESTLEIND": ["Nestle India"],
    "BRITANNIA": ["Britannia"],
    "TATACONSUM": ["Tata Consumer"],
    "ASIANPAINT": ["Asian Paints"],
    "TITAN": ["Titan Company", "Titan"],
    "ULTRACEMCO": ["UltraTech Cement", "UltraTech"],
    "GRASIM": ["Grasim"],
    "LT": ["Larsen & Toubro", "Larsen and Toubro", "L&T"],
    "ADANIENT": ["Adani Enterprises"],
    "ADANIPORTS": ["Adani Ports"],
    "BHARTIARTL": ["Bharti Airtel", "Airtel"],
    "SUNPHARMA": ["Sun Pharma", "Sun Pharmaceutical"],
    "DRREDDY": ["Dr Reddy's", "Dr. Reddy's"],
    "CIPLA": ["Cipla"],
    "DIVISLAB": ["Divi's Laboratories", "Divi's Labs"],
    "APOLLOHOSP": ["Apollo Hospitals"],
    "ETERNAL": ["Eternal", "Zomato"],
    "ZOMATO": ["Zomato", "Eternal"],
    "POLICYBZR": ["PB Fintech", "Policybazaar"],
    "PAYTM": ["Paytm", "One 97 Communications"],
    "NYKAA": ["Nykaa", "FSN E-Commerce"],
    "IRCTC": ["IRCTC"],
    "HAL": ["Hindustan Aeronautics"],
    "BEL": ["Bharat Electronics"],
    "DMART": ["Avenue Supermarts", "DMart"],
    "TRENT": ["Trent"],
    "SHRIRAMFIN": ["Shriram Finance"],
}

# Words that, right after an alias, mean a *different* company: "SBI Life", "HDFC Life", "ICICI Prudential"...
# An article counts as a mention only if some occurrence of an alias is not followed by one of these.
NOT_FOLLOWED_BY = {
    "SBIN": ["Life", "Card", "Cards", "Mutual", "MF", "Funds", "Fund", "Securities", "General", "Caps", "Pension", "Foundation",
             "USMNT", "USWNT", "Holdings", "Shinsei", "Man of the Match", "Player"],
    "TCS": ["Rapid Cycling", "Marathon", "World 10K", "London Marathon", "Amsterdam Marathon"],
    "HDFCBANK": ["Life", "AMC", "Mutual", "Securities", "Ergo", "Credila"],
    "ICICIBANK": ["Prudential", "Lombard", "Securities", "Pru"],
    "KOTAKBANK": ["Mahindra Life", "Securities", "Mutual"],
    "AXISBANK": ["Mutual", "Securities", "Max Life", "Finance"],
    "BAJAJFINSV": [],
    "RELIANCE": ["Power", "Infrastructure", "Infra", "Capital", "Communications", "Home Finance", "General", "Nippon", "Retail Ventures"],
    "LT": ["Finance", "Technology Services", "Tech", "Mindtree"],
    "TATAMOTORS": ["Finance"],
}

INDEX_NAMES = {"^NSEI": ["Nifty 50", "Nifty"], "^BSESN": ["Sensex"]}

_SUFFIXES = {"LIMITED", "LTD", "LT", "INC", "CORPORATION", "CORP", "CO", "PLC"}


def symbol(ticker: str) -> str:
    return ticker.upper().split(".")[0]


def _clean(name: str) -> str:
    words = [w for w in re.split(r"\s+", name.replace(".", " ").strip()) if w and w.upper() not in _SUFFIXES]
    cleaned = " ".join(words).strip()
    return cleaned.title() if cleaned.isupper() else cleaned


@lru_cache(maxsize=512)
def _yf_name(ticker: str) -> str:
    """longName first: shortName is often truncated ('Tata Consultancy Serv Lt')."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        name = info.get("longName") or info.get("shortName") or ""
        return _clean(name)
    except Exception:
        return ""


def aliases(ticker: str) -> List[str]:
    """All names to search for / match against, canonical first."""
    if ticker in INDEX_NAMES:
        return list(INDEX_NAMES[ticker])
    sym = symbol(ticker)
    names = list(ALIASES.get(sym, []))
    if not names:
        yf_name = _yf_name(ticker)
        if yf_name:
            names.append(yf_name)
        names.append(sym)
    return names


def company_name(ticker: str) -> str:
    return aliases(ticker)[0]


def news_query(ticker: str) -> str:
    """NewsAPI query: exact phrases OR-ed together, e.g. '"State Bank of India" OR "SBI"'."""
    return " OR ".join(f'"{a}"' for a in aliases(ticker)[:3])


def _pattern(alias: str, excluded=()) -> re.Pattern:
    # Whole-word match; tolerate a possessive ("Infosys's") and flexible whitespace.
    # Multi-word names match case-insensitively. Single words ("Wipro", "Eternal", "TCS") must keep their
    # capitalisation (or be all caps) so ordinary words ("eternal", "titan") don't count as mentions.
    parts = alias.split()
    body = r"\s+".join(re.escape(p) for p in parts)
    edge_l, edge_r = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
    if excluded:
        edge_r += r"(?!\s+(?:" + "|".join(r"\s+".join(map(re.escape, w.split())) for w in excluded) + r")(?![A-Za-z0-9]))"
    if len(parts) > 1:
        return re.compile(rf"{edge_l}{body}{edge_r}", re.IGNORECASE)
    variants = {re.escape(alias), re.escape(alias.upper())}
    return re.compile(rf"{edge_l}(?:{'|'.join(sorted(variants))}){edge_r}")


@lru_cache(maxsize=512)
def _patterns(ticker: str):
    excluded = NOT_FOLLOWED_BY.get(symbol(ticker), [])
    return [_pattern(a, excluded) for a in aliases(ticker)]


def mentions(text: str, ticker: str) -> bool:
    """True if the text names the company (whole-word match on any alias)."""
    return any(p.search(text or "") for p in _patterns(ticker))


def is_english(text: str) -> bool:
    """NewsAPI's language=en still lets through e.g. Japanese 'SBI証券' press releases."""
    letters = [ch for ch in text or "" if ch.isalpha()]
    return bool(letters) and sum(1 for ch in letters if ch.isascii()) / len(letters) >= 0.8


def about(title: str, ticker: str) -> bool:
    """An article counts for a stock only if its *headline* names the company. Names that only appear in the
    description are usually market round-ups ("Day Trading Guide", "Stocks to watch") or passing mentions."""
    return is_english(title) and mentions(title, ticker)
