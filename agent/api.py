"""FastAPI: панель владельца. Запуск: uvicorn agent.api:app --reload"""
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crm, pipeline, reports
from .catalog import get_catalog
from .collectors import parse_pasted
from .db import Job, Proposal, Stage, make_session_factory
from .llm import LLMError
from .settings import get_settings

app = FastAPI(title="Freelance Agent")
_factory = None


def get_session():
    global _factory
    if _factory is None:
        _factory = make_session_factory()
    with _factory() as s:
        yield s


class ImportIn(BaseModel):
    platform: str
    text: str
    url: str = ""


class StageIn(BaseModel):
    stage: Stage
    note: str = ""
    contract_value: float | None = None


def _job_out(j: Job) -> dict:
    return {
        "id": j.id, "platform": j.platform, "title": j.title, "url": j.url, "language": j.language,
        "budget": [j.budget_min, j.budget_max, j.currency, j.budget_type], "score": j.score,
        "service_id": j.service_id, "stage": j.stage, "score_details": j.score_details,
    }


def _get_job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.get("/jobs")
def list_jobs(stage: Stage | None = None, min_score: float = 0, session: Session = Depends(get_session)):
    q = select(Job).order_by(Job.score.desc().nullslast(), Job.collected_at.desc())
    if stage:
        q = q.where(Job.stage == stage)
    return [_job_out(j) for j in session.scalars(q) if (j.score or 0) >= min_score]


@app.post("/jobs/import")
def import_job(body: ImportIn, llm: bool = False, session: Session = Depends(get_session)):
    """Вставить текст заказа / письма-алерта; заказ сразу оценивается."""
    new = pipeline.ingest(session, [parse_pasted(body.platform, body.text, body.url)])
    if not new:
        raise HTTPException(409, "already imported")
    job = pipeline.score_and_route(session, new[0], get_catalog(), get_settings(), use_llm=llm)
    session.commit()
    return _job_out(job)


@app.post("/jobs/{job_id}/draft")
def draft(job_id: int, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    try:
        p = pipeline.draft(session, job, get_catalog(), get_settings())
    except LLMError as e:
        raise HTTPException(502, str(e))
    session.commit()
    return {"proposal_id": p.id, "text": p.text, "questions": p.questions, "price": p.price, "price_note": p.price_note}


@app.get("/jobs/{job_id}/proposals")
def proposals(job_id: int, session: Session = Depends(get_session)):
    _get_job(session, job_id)
    rows = session.scalars(select(Proposal).where(Proposal.job_id == job_id).order_by(Proposal.created_at.desc()))
    return [{"id": p.id, "text": p.text, "questions": p.questions, "price": p.price, "created_at": p.created_at}
            for p in rows]


@app.post("/jobs/{job_id}/stage")
def move_stage(job_id: int, body: StageIn, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    try:
        crm.move(session, job, body.stage, body.note, contract_value=body.contract_value)
    except crm.TransitionError as e:
        raise HTTPException(400, str(e))
    session.commit()
    return _job_out(job)


@app.post("/collect")
def collect(llm: bool = False, session: Session = Depends(get_session)):
    return pipeline.run_collection(session, get_catalog(), get_settings(), use_llm=llm)


@app.get("/reports/summary")
def summary(days: int = 7, session: Session = Depends(get_session)):
    return reports.summary(session, days)
