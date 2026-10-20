"""М5: расчёт цены предложения. Прозрачные правила, каждое решение пишется в notes."""
from dataclasses import dataclass, field

from .catalog import Catalog, to_usd
from .db import Job
from .scoring import extract_quantity

URGENT = ("urgent", "asap", "24 hours", "48 hours", "tomorrow", "срочно", "сегодня", "завтра",
          "pilne", "na jutro", "терміново", "сьогодні")
URGENCY_MULT = 1.3
WORDS_PER_PAGE = 275


@dataclass
class Quote:
    price: float
    currency: str = "USD"
    notes: list[str] = field(default_factory=list)

    @property
    def note(self) -> str:
        return "; ".join(self.notes)


def quote(job: Job, catalog: Catalog, service_id: str | None = None) -> Quote | None:
    service_id = service_id or job.service_id
    if not service_id:
        return None
    s = catalog.services[service_id]
    rates = (catalog.profile or {}).get("rates") or {}
    typical = float(rates.get(service_id, s.price_typical))
    notes = []
    text = f"{job.title}\n{job.description}".lower()

    if s.unit in ("page", "1000_words"):
        qty, qty_unit = extract_quantity(text)
        if qty is None:
            price = typical * (10 if s.unit == "page" else 5)
            notes.append(f"объём не указан — база как за {'10 стр.' if s.unit == 'page' else '5000 слов'}, уточнить у клиента")
        else:
            if s.unit == "page":
                pages = qty if qty_unit == "pages" else qty / WORDS_PER_PAGE
                price = typical * pages
                notes.append(f"{pages:.0f} стр. × ${typical}")
            else:
                words = qty if qty_unit == "words" else qty * WORDS_PER_PAGE
                price = typical * words / 1000
                notes.append(f"{words:.0f} слов × ${typical}/1000")
    elif s.unit == "hour":
        price = typical
        notes.append(f"почасово ${typical}/ч")
    else:
        price = typical
        notes.append(f"типовая цена услуги ${typical}")

    if any(u in text for u in URGENT):
        price *= URGENCY_MULT
        notes.append(f"срочность ×{URGENCY_MULT}")

    if s.unit != "hour":
        floor = s.price_min if s.unit == "project" else s.price_min * 10
        if price < floor:
            price = floor
            notes.append(f"поднято до минимума ${floor}")

    # Попасть в бюджет клиента, если он не ниже 80% нашей цены
    budget = to_usd(job.budget_max or job.budget_min, job.currency)
    if budget and job.budget_type != "hourly" and s.unit != "hour":
        if budget >= price:
            price = min(budget, price * 1.15)
            notes.append("бюджет клиента выше расчёта — цена ближе к бюджету")
        elif budget >= 0.8 * price:
            price = budget
            notes.append("цена = бюджет клиента (≤20% ниже расчёта)")
        else:
            notes.append(f"бюджет клиента ${budget:.0f} сильно ниже расчёта — предложить сокращённый объём")

    platform = catalog.platforms.get(job.platform)
    if platform and platform.fee_pct:
        notes.append(f"на руки после комиссии {platform.fee_pct:g}%: ${price * (1 - platform.fee_pct / 100):.0f}")

    return Quote(price=round(price / 5) * 5 or round(price, 2), currency="USD", notes=notes)
