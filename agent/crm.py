"""М6: воронка заказов. Переходы между этапами проверяются и журналируются."""
from sqlalchemy.orm import Session

from .db import Job, Stage, StageEvent, utcnow

ALLOWED = {
    Stage.NEW: {Stage.QUALIFIED, Stage.SKIPPED},
    Stage.QUALIFIED: {Stage.DRAFTED, Stage.SKIPPED},
    Stage.DRAFTED: {Stage.SENT, Stage.SKIPPED, Stage.DRAFTED},
    Stage.SENT: {Stage.REPLIED, Stage.WON, Stage.LOST},  # клиент может нанять сразу
    Stage.REPLIED: {Stage.INTERVIEW, Stage.WON, Stage.LOST},
    Stage.INTERVIEW: {Stage.WON, Stage.LOST},
    Stage.WON: {Stage.DELIVERED, Stage.LOST},
    Stage.DELIVERED: {Stage.REVIEWED},
    Stage.REVIEWED: set(),
    Stage.LOST: set(),
    Stage.SKIPPED: {Stage.QUALIFIED},  # владелец может вернуть заказ
}


class TransitionError(ValueError):
    pass


def move(session: Session, job: Job, to: Stage, note: str = "", *, contract_value: float | None = None) -> Job:
    current = job.stage or Stage.NEW  # у ещё не сохранённого заказа default не применён
    if to not in ALLOWED[current]:
        raise TransitionError(f"{current} → {to} не разрешён")
    session.add(StageEvent(job=job, from_stage=current, to_stage=to, note=note))
    job.stage = to
    job.stage_changed_at = utcnow()
    if contract_value is not None:
        job.contract_value = contract_value
    return job
