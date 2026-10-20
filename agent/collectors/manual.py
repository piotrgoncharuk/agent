"""Ручной ввод: вставленный текст заказа или e-mail-алерта (Upwork, Kolabtree, LinkedIn…)."""
import hashlib
import re

from .base import JobIn

_BUDGET = re.compile(r"(?:budget|бюджет|budżet)[^\d$€£]{0,20}([$€£]|usd|eur|pln|uah|zł|грн)?\s*([\d\s,.]+)(?:\s*[-–]\s*(?:[$€£]|usd|eur|pln|uah)?\s*([\d\s,.]+))?\s*(zł|pln|грн|uah|usd|eur|€)?", re.I)
_HOURLY = re.compile(r"hourly|/hr|per hour|в час|за годину|za godzinę", re.I)
_CUR = {"$": "USD", "€": "EUR", "£": "GBP", "zł": "PLN", "грн": "UAH"}


def _num(s: str | None) -> float | None:
    if not s:
        return None
    s = re.sub(r"[\s,]", "", s).rstrip(".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_pasted(platform: str, text: str, url: str = "") -> JobIn:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    title = lines[0][:512] if lines else "(без названия)"
    body = "\n".join(lines[1:])
    m = _BUDGET.search(text)
    lo = hi = None
    currency = "USD"
    if m:
        cur = (m.group(1) or m.group(4) or "").lower()
        currency = _CUR.get(cur, cur.upper() or "USD")
        lo, hi = _num(m.group(2)), _num(m.group(3))
        if hi is None:
            lo, hi = None, lo
    ext = hashlib.sha1((url or text).encode()).hexdigest()[:16]
    return JobIn(platform=platform, external_id=ext, title=title, description=body, url=url,
                 budget_min=lo, budget_max=hi, currency=currency,
                 budget_type="hourly" if _HOURLY.search(text) else ("fixed" if m else "unknown"))
