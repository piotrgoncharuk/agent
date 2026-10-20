"""М7: сводка по воронке и сравнение с целевыми метриками ТЗ."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Job, Stage, StageEvent

TARGETS = {
    "qualified_per_day": 10,
    "conversion_min": 0.03,
    "conversion_max": 0.05,
    "revenue_usd": 10_000,
    "revenue_deadline": date(2026, 12, 11),
    "five_star_reviews": 3,
    "reviews_deadline": date(2026, 11, 15),
}

_REACHED_SENT = {Stage.SENT, Stage.REPLIED, Stage.INTERVIEW, Stage.WON, Stage.DELIVERED, Stage.REVIEWED, Stage.LOST}
_REACHED_WON = {Stage.WON, Stage.DELIVERED, Stage.REVIEWED}


def summary(session: Session, days: int = 7) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    jobs = session.scalars(select(Job)).all()
    recent = [j for j in jobs if _aware(j.collected_at) >= since]

    qualified_events = session.scalars(
        select(StageEvent).where(StageEvent.to_stage == Stage.QUALIFIED, StageEvent.at >= since)
    ).all()
    sent = [j for j in jobs if j.stage in _REACHED_SENT]
    won = [j for j in jobs if j.stage in _REACHED_WON]
    revenue = sum(j.contract_value or 0 for j in won)
    conversion = len(won) / len(sent) if sent else 0.0

    by_platform = {}
    for p in sorted({j.platform for j in jobs}):
        pj = [j for j in jobs if j.platform == p]
        ps = [j for j in pj if j.stage in _REACHED_SENT]
        pw = [j for j in pj if j.stage in _REACHED_WON]
        by_platform[p] = {
            "collected": len(pj),
            "sent": len(ps),
            "won": len(pw),
            "conversion": round(len(pw) / len(ps), 3) if ps else None,
            "revenue": sum(j.contract_value or 0 for j in pw),
        }

    today = date.today()
    days_left = (TARGETS["revenue_deadline"] - today).days
    return {
        "period_days": days,
        "collected": len(recent),
        "qualified_per_day": round(len(qualified_events) / days, 1),
        "stages": dict(Counter(j.stage.value for j in jobs)),
        "sent_total": len(sent),
        "won_total": len(won),
        "conversion": round(conversion, 3),
        "revenue_usd": revenue,
        "revenue_needed_per_day": round(max(0, TARGETS["revenue_usd"] - revenue) / days_left, 0) if days_left > 0 else None,
        "reviews": sum(1 for j in jobs if j.stage == Stage.REVIEWED),
        "by_platform": by_platform,
        "targets": {k: str(v) if isinstance(v, date) else v for k, v in TARGETS.items()},
    }


def format_text(s: dict) -> str:
    t = s["targets"]
    lines = [
        f"📊 Отчёт за {s['period_days']} дн.",
        f"Собрано: {s['collected']} | квалиф./день: {s['qualified_per_day']} (цель {t['qualified_per_day']})",
        f"Отправлено: {s['sent_total']} | контрактов: {s['won_total']} | конверсия: {s['conversion']:.1%} "
        f"(цель {t['conversion_min']:.0%}–{t['conversion_max']:.0%})",
        f"Выручка: ${s['revenue_usd']:,.0f} из ${t['revenue_usd']:,} к {t['revenue_deadline']}"
        + (f" — нужно ~${s['revenue_needed_per_day']:,.0f}/день" if s["revenue_needed_per_day"] else ""),
        f"Отзывы: {s['reviews']} (цель {t['five_star_reviews']} к {t['reviews_deadline']})",
    ]
    for p, d in s["by_platform"].items():
        conv = f"{d['conversion']:.0%}" if d["conversion"] is not None else "—"
        lines.append(f"  • {p}: {d['collected']} собр., {d['sent']} отпр., {d['won']} контр., конв. {conv}, ${d['revenue']:,.0f}")
    return "\n".join(lines)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
