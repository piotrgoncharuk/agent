"""Уведомления в Telegram (Bot API). Без токена — тихо пропускаем."""
import logging

import httpx

from .db import Job
from .settings import get_settings

log = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        log.info("telegram not configured; message:\n%s", text)
        return False
    r = httpx.post(
        f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
        json={"chat_id": s.telegram_chat_id, "text": text[:4000], "disable_web_page_preview": True},
        timeout=15,
    )
    if r.status_code != 200:
        log.warning("telegram error %s: %s", r.status_code, r.text[:200])
    return r.status_code == 200


def job_card(job: Job) -> str:
    budget = f"{job.budget_min or '?'}–{job.budget_max or '?'} {job.currency}" if (job.budget_min or job.budget_max) else "не указан"
    return (
        f"🆕 [{job.score:.0f}] {job.title}\n"
        f"{job.platform} · {job.language} · {job.service_id or '—'} · бюджет {budget}\n"
        f"{job.url}\n#job{job.id}"
    )
