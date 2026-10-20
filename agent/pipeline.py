"""Конвейер: сбор → дедупликация → скоринг → уведомление → (по запросу) черновик отклика."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crm, notify
from .catalog import Catalog
from .collectors import FreelancehuntCollector, FreelancerCollector, JobIn, RSSCollector
from .db import Job, Proposal, Stage
from .lang import detect_language
from .pricing import quote
from .proposals import draft_proposal
from .scoring import score_job
from .settings import Settings

log = logging.getLogger(__name__)


def build_collectors(settings: Settings, catalog: Catalog) -> list:
    collectors = []
    for p in catalog.platforms.values():
        if p.collector == "rss" and p.feeds:
            collectors.append(RSSCollector(p.id, p.feeds))
    if settings.freelancehunt_token:
        collectors.append(FreelancehuntCollector(settings.freelancehunt_token))
    if settings.freelancer_token:
        collectors.append(FreelancerCollector(settings.freelancer_token))
    return collectors


def ingest(session: Session, items: list[JobIn]) -> list[Job]:
    """Сохраняет новые заказы, пропуская уже известные (platform, external_id)."""
    new = []
    for it in items:
        exists = session.scalar(select(Job.id).where(Job.platform == it.platform, Job.external_id == it.external_id))
        if exists:
            continue
        job = Job(**it.model_dump(), language=detect_language(f"{it.title}\n{it.description}"))
        session.add(job)
        new.append(job)
    session.flush()
    return new


def score_and_route(session: Session, job: Job, catalog: Catalog, settings: Settings, *, use_llm: bool = False) -> Job:
    result = score_job(job, catalog, llm_model=settings.model_scorer if use_llm else None)
    job.score = result.total
    job.service_id = result.service_id
    job.score_details = result.as_details()
    if (job.stage or Stage.NEW) == Stage.NEW:
        qualified = result.total >= settings.score_notify_threshold and not result.red_flags
        crm.move(session, job, Stage.QUALIFIED if qualified else Stage.SKIPPED, note=f"score {result.total}")
        if qualified:
            notify.send_job(job)
    return job


def draft(session: Session, job: Job, catalog: Catalog, settings: Settings) -> Proposal:
    q = quote(job, catalog)
    d = draft_proposal(job, catalog, q, model=settings.model_writer)
    p = Proposal(job=job, language=job.language, text=d.text, questions=d.questions,
                 price=q.price if q else None, price_note=q.note if q else "", model=settings.model_writer)
    session.add(p)
    note = f"decline: {d.decline_reason}" if d.decline else f"~{d.estimated_days} дн."
    if job.stage in (Stage.QUALIFIED, Stage.DRAFTED):
        crm.move(session, job, Stage.DRAFTED, note=note)
    return p


def run_collection(session: Session, catalog: Catalog, settings: Settings, *, use_llm: bool = False) -> dict:
    stats = {"fetched": 0, "new": 0, "qualified": 0, "errors": []}
    for c in build_collectors(settings, catalog):
        try:
            items = c.fetch()
        except Exception as e:  # один упавший источник не должен останавливать остальные
            log.exception("collector %s failed", c.platform)
            stats["errors"].append(f"{c.platform}: {e}")
            continue
        stats["fetched"] += len(items)
        for job in ingest(session, items):
            stats["new"] += 1
            score_and_route(session, job, catalog, settings, use_llm=use_llm)
            stats["qualified"] += job.stage == Stage.QUALIFIED
    session.commit()
    return stats
