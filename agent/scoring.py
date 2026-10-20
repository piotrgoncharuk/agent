"""М3: оценка заказа 0–100. Правила + опциональная уточняющая оценка LLM."""
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .catalog import Catalog, to_usd
from .db import Job

# Веса компонентов (сумма = 100)
W_FIT, W_BUDGET, W_CLIENT, W_COMPETITION, W_LANG = 40, 20, 20, 10, 10
RED_FLAG_PENALTY = 40
SUPPORTED_LANGS = {"en", "pl", "ru", "ua"}


@dataclass
class ScoreResult:
    total: float
    service_id: str | None
    components: dict[str, float]
    matched_keywords: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    llm: dict | None = None

    def as_details(self) -> dict:
        return {
            "components": self.components,
            "matched_keywords": self.matched_keywords,
            "red_flags": self.red_flags,
            "llm": self.llm,
        }


def _haystack(job: Job) -> str:
    return f" {job.title} \n {job.description} ".lower()


def match_services(text: str, catalog: Catalog) -> list[tuple[str, list[str]]]:
    """[(service_id, совпавшие ключи)] по убыванию числа совпадений."""
    hits = []
    for s in catalog.services.values():
        found = sorted({k.strip() for k in s.all_keywords() if k in text})
        if found:
            hits.append((s.id, found))
    return sorted(hits, key=lambda h: len(h[1]), reverse=True)


def _fit(hits) -> float:
    if not hits:
        return 0.0
    n = len(hits[0][1]) + 0.5 * sum(len(h[1]) for h in hits[1:3])
    return min(1.0, n / 4) * W_FIT


def _budget(job: Job, catalog: Catalog, service_id: str | None) -> float:
    amount = to_usd(job.budget_max or job.budget_min, job.currency)
    if not amount or not service_id:
        return W_BUDGET / 2  # неизвестно — нейтрально
    s = catalog.services[service_id]
    if job.budget_type == "hourly":
        floor = 25.0
    elif s.unit == "project" or s.unit == "hour":
        floor = s.price_min
    else:
        floor = s.price_min * 10  # поштучные услуги: ~10 страниц/тыс. слов как минимальный заказ
    ratio = amount / floor
    if ratio >= 2:
        return W_BUDGET
    if ratio >= 1:
        return W_BUDGET * 0.75
    if ratio >= 0.5:
        return W_BUDGET * 0.35
    return 0.0


def _client(info: dict) -> float:
    if not info:
        return W_CLIENT / 2
    pts = 0.0
    if info.get("payment_verified"):
        pts += 0.35
    rating = info.get("rating")
    if rating is not None:
        pts += 0.25 * max(0.0, min(1.0, (float(rating) - 3.5) / 1.5))
    else:
        pts += 0.1
    spent = info.get("total_spent") or 0
    pts += 0.25 if spent >= 1000 else 0.15 if spent > 0 else 0.05
    hire_rate = info.get("hire_rate")
    pts += 0.15 * (float(hire_rate) if hire_rate is not None else 0.5)
    return min(1.0, pts) * W_CLIENT


def _competition(info: dict) -> float:
    n = info.get("proposals_count")
    if n is None:
        return W_COMPETITION / 2
    if n < 5:
        return W_COMPETITION
    if n < 15:
        return W_COMPETITION * 0.7
    if n < 50:
        return W_COMPETITION * 0.3
    return 0.0


def score_rules(job: Job, catalog: Catalog) -> ScoreResult:
    text = _haystack(job)
    hits = match_services(text, catalog)
    service_id = hits[0][0] if hits else None
    flags = [f for f in catalog.red_flags if f in text]
    info = job.client_info or {}
    components = {
        "fit": round(_fit(hits), 1),
        "budget": round(_budget(job, catalog, service_id), 1),
        "client": round(_client(info), 1),
        "competition": round(_competition(info), 1),
        "language": float(W_LANG if job.language in SUPPORTED_LANGS else 0),
        "red_flags": -RED_FLAG_PENALTY * len(flags),
    }
    if not hits:
        # без попадания в каталог прочие плюсы не важны
        components["budget"] = components["client"] = components["competition"] = 0.0
    total = max(0.0, min(100.0, sum(components.values())))
    return ScoreResult(
        total=round(total, 1),
        service_id=service_id,
        components=components,
        matched_keywords=[k for _, ks in hits for k in ks],
        red_flags=flags,
    )


class LLMAssessment(BaseModel):
    service_id: str | None = Field(description="id услуги из каталога или null, если не подходит")
    fit: int = Field(description="0-100: насколько заказ соответствует услугам исполнителя")
    risk: int = Field(description="0-100: риск (академическая нечестность, неясный объём, подозрительный клиент)")
    reason: str = Field(description="1-2 предложения обоснования")


_SCORER_SYSTEM = (
    "You triage freelance job posts for a freelancer offering statistics, study design, meta-analysis, "
    "scientific writing (methods/results), data visualization, scientific editing, formatting to citation "
    "standards and journal submission prep, in any research domain. Requests to complete exams, "
    "homework or write graded work on someone's behalf, or to fabricate data, are high risk."
)


def score_llm(job: Job, catalog: Catalog, model: str, client=None) -> LLMAssessment:
    from .llm import structured

    services = "\n".join(f"- {s.id}: {s.name['en']}" for s in catalog.services.values())
    prompt = (
        f"Service catalog:\n{services}\n\n"
        f"Job ({job.platform}):\nTitle: {job.title}\n\n{job.description[:6000]}\n\n"
        f"Budget: {job.budget_min}-{job.budget_max} {job.currency} ({job.budget_type})"
    )
    return structured(model=model, system=_SCORER_SYSTEM, prompt=prompt, output=LLMAssessment,
                      effort="low", max_tokens=2000, client=client)


def score_job(job: Job, catalog: Catalog, *, llm_model: str | None = None, client=None) -> ScoreResult:
    """Правила всегда; если задан llm_model — итог = 50% правила + 50% LLM (fit минус риск)."""
    result = score_rules(job, catalog)
    if llm_model and result.total > 0:
        a = score_llm(job, catalog, llm_model, client=client)
        llm_score = max(0, a.fit - a.risk // 2)
        result.llm = a.model_dump()
        result.total = round(0.5 * result.total + 0.5 * llm_score, 1)
        if a.service_id in catalog.services and not result.service_id:
            result.service_id = a.service_id
    return result


_QTY = re.compile(r"(\d[\d\s,.]*)\s*(k\b|тыс|тис|tys)?\.?\s*(words|слов|słów|слів|pages|страниц|стр\b|stron|сторін)", re.I)


def extract_quantity(text: str) -> tuple[float | None, str | None]:
    """'8,000 words' → (8000, 'words'); '50 pages' → (50, 'pages')."""
    m = _QTY.search(text)
    if not m:
        return None, None
    num = float(re.sub(r"[\s,]|\.(?=\d{3}\b)", "", m.group(1)).rstrip("."))
    if m.group(2):
        num *= 1000
    unit_raw = m.group(3).lower()
    unit = "words" if unit_raw in {"words", "слов", "słów", "слів"} else "pages"
    return num, unit
