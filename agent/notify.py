"""Telegram Bot API: отправка сообщений, карточки заказов с кнопками."""
import logging

import httpx

from .db import Job, Stage
from .settings import get_settings

log = logging.getLogger(__name__)

TG_LIMIT = 4096


class TelegramAPI:
    def __init__(self, token: str, http: httpx.Client | None = None):
        self.token = token
        self.http = http or httpx.Client(timeout=40)

    def call(self, method: str, **params) -> dict | list | bool | None:
        r = self.http.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not data.get("ok"):
            log.warning("telegram %s failed: %s", method, str(data or r.text)[:300])
            return None
        return data.get("result")


_api: TelegramAPI | None = None


def get_api() -> TelegramAPI | None:
    global _api
    s = get_settings()
    if not s.telegram_bot_token:
        return None
    if _api is None:
        _api = TelegramAPI(s.telegram_bot_token)
    return _api


def split_text(text: str, limit: int = TG_LIMIT - 96) -> list[str]:
    """Режет длинный текст по абзацам/строкам, чтобы уложиться в лимит Telegram."""
    parts, rest = [], text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    parts.append(rest)
    return parts


def send_telegram(text: str, reply_markup: dict | None = None, chat_id: str | None = None) -> dict | None:
    """Отправляет текст (с разбиением). Кнопки крепятся к последней части."""
    api, s = get_api(), get_settings()
    chat_id = chat_id or s.telegram_chat_id
    if not (api and chat_id):
        log.info("telegram not configured; message:\n%s", text)
        return None
    parts = split_text(text)
    msg = None
    for i, part in enumerate(parts):
        params = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
        if reply_markup and i == len(parts) - 1:
            params["reply_markup"] = reply_markup
        msg = api.call("sendMessage", **params)
    return msg


def _btn(text: str, action: str, job_id: int) -> dict:
    return {"text": text, "callback_data": f"{action}:{job_id}"}


def keyboard(job: Job) -> dict | None:
    """Кнопки зависят от этапа воронки: всегда только допустимые следующие шаги."""
    i = job.id
    rows = {
        Stage.QUALIFIED: [[_btn("✍️ Черновик", "draft", i), _btn("⏭ Пропустить", "skip", i)]],
        Stage.DRAFTED: [[_btn("✅ Отправил", "sent", i), _btn("🔁 Переписать", "draft", i)],
                        [_btn("⏭ Пропустить", "skip", i)]],
        Stage.SENT: [[_btn("💬 Клиент ответил", "replied", i), _btn("❌ Не взяли", "lost", i)]],
        Stage.REPLIED: [[_btn("🤝 Контракт", "won", i), _btn("🗣 Переговоры", "interview", i)],
                        [_btn("❌ Не взяли", "lost", i)]],
        Stage.INTERVIEW: [[_btn("🤝 Контракт", "won", i), _btn("❌ Не взяли", "lost", i)]],
        Stage.WON: [[_btn("📦 Сдал работу", "delivered", i)]],
        Stage.DELIVERED: [[_btn("⭐ Получил отзыв", "reviewed", i)]],
        Stage.SKIPPED: [[_btn("↩️ Вернуть", "restore", i)]],
    }.get(job.stage)
    return {"inline_keyboard": rows} if rows else None


def job_card(job: Job) -> str:
    budget = (f"{job.budget_min or '?'}–{job.budget_max or '?'} {job.currency}"
              if (job.budget_min or job.budget_max) else "не указан")
    details = job.score_details or {}
    flags = details.get("red_flags") or []
    kws = ", ".join((details.get("matched_keywords") or [])[:6])
    lines = [
        f"🆕 [{job.score or 0:.0f}] {job.title}",
        f"{job.platform} · {job.language} · {job.service_id or '—'} · бюджет {budget}",
        f"этап: {job.stage.value if job.stage else 'new'}",
    ]
    if kws:
        lines.append(f"совпадения: {kws}")
    if flags:
        lines.append(f"⚠️ {', '.join(flags)}")
    if job.description:
        snippet = job.description[:400].replace("\n", " ")
        lines.append(f"\n{snippet}{'…' if len(job.description) > 400 else ''}")
    if job.url:
        lines.append(job.url)
    lines.append(f"#job{job.id}")
    return "\n".join(lines)


def send_job(job: Job) -> dict | None:
    return send_telegram(job_card(job), reply_markup=keyboard(job))
