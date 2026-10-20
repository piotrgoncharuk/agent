"""М4: черновик отклика на языке заказа. Отправляет всегда владелец."""
import yaml
from pydantic import BaseModel, Field

from .catalog import Catalog
from .db import Job
from .llm import structured
from .pricing import Quote

LANG_NAMES = {"en": "English", "pl": "Polish", "ru": "Russian", "ua": "Ukrainian"}

SYSTEM = """You write freelance proposals for a scientific statistics & editing specialist.

Rules:
- Write in {language}. Natural, professional, no clichés ("I am the perfect fit", "Dear Sir/Madam").
- Open with the client's actual problem in one or two sentences — show you read the post.
- Then: a concrete approach (named methods/tools that fit THIS task), what they will receive, a realistic timeline.
- Use ONLY facts from the freelancer profile. Never invent degrees, employers, publications, numbers of
  clients or reviews. If a fact would help but the profile field is a [placeholder] or empty, leave the
  bracketed placeholder in the text so the owner fills it in.
- Ask 1–3 short clarifying questions that affect scope or price (put them in `questions`, and weave the
  most important one into the text).
- Do not offer to do graded coursework or exams; if the post asks for that, set `decline` to true.
- Hard length limit: {limit} characters for `text`. Shorter is better: 120–220 words is the target.
- Mention the price only if one is given below; do not discuss platform fees."""


class ProposalDraft(BaseModel):
    text: str = Field(description="текст отклика")
    questions: list[str] = Field(description="1-3 уточняющих вопроса клиенту")
    estimated_days: int = Field(description="реалистичный срок в днях")
    decline: bool = Field(description="true, если заказ не стоит брать (этика/не наш профиль)")
    decline_reason: str = Field(description="причина отказа или пустая строка")


def _limit(job: Job, catalog: Catalog) -> int:
    p = catalog.platforms.get(job.platform)
    if p and p.proposal_limits:
        return min(p.proposal_limits.values())
    return 3000


def draft_proposal(job: Job, catalog: Catalog, quote: Quote | None, *, model: str, client=None) -> ProposalDraft:
    lang = job.language if job.language in LANG_NAMES else "en"
    limit = _limit(job, catalog)
    service = catalog.services.get(job.service_id or "")
    profile = yaml.safe_dump(catalog.profile, allow_unicode=True, sort_keys=False)
    price_line = f"Proposed price: ${quote.price:.0f} ({quote.note})" if quote else "Price: not set — do not mention a number."
    prompt = (
        f"<profile>\n{profile}</profile>\n\n"
        f"<matched_service>{service.name['en'] if service else 'unknown'}</matched_service>\n"
        f"<pricing>{price_line}</pricing>\n\n"
        f"<job platform=\"{job.platform}\">\nTitle: {job.title}\n\n{job.description[:8000]}\n</job>"
    )
    draft = structured(
        model=model,
        system=SYSTEM.format(language=LANG_NAMES[lang], limit=limit),
        prompt=prompt,
        output=ProposalDraft,
        effort="medium",
        client=client,
    )
    if len(draft.text) > limit:
        draft.text = draft.text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return draft
