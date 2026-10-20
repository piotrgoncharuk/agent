"""Telegram-бот: кнопки воронки и команды. Отвечает только владельцу (TELEGRAM_CHAT_ID)."""
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crm, notify, pipeline, reports
from .catalog import Catalog
from .collectors import parse_pasted
from .db import Job, Proposal, Stage
from .llm import LLMError
from .settings import Settings

log = logging.getLogger(__name__)

HELP = """Команды:
/jobs — заказы, ждущие решения (квалифицированные и черновики)
/job 12 — карточка заказа #12
/add upwork — со следующей строки вставьте текст заказа (ссылку можно включить в текст)
/won 12 450 — контракт по заказу #12 на $450
/collect — собрать заказы сейчас
/report [дни] — отчёт по воронке (по умолчанию 7 дней)
/help — эта справка

Кнопки под карточкой двигают заказ по воронке:
✍️ Черновик → ✅ Отправил → 💬 Ответил → 🤝 Контракт → 📦 Сдал → ⭐ Отзыв"""

# действие кнопки → целевой этап (draft/won обрабатываются отдельно)
SIMPLE_MOVES = {
    "skip": Stage.SKIPPED, "sent": Stage.SENT, "replied": Stage.REPLIED, "interview": Stage.INTERVIEW,
    "lost": Stage.LOST, "delivered": Stage.DELIVERED, "reviewed": Stage.REVIEWED, "restore": Stage.QUALIFIED,
}
URL_RE = re.compile(r"https?://\S+")


class Bot:
    def __init__(self, api: notify.TelegramAPI, session_factory, catalog: Catalog, settings: Settings):
        self.api = api
        self.session_factory = session_factory
        self.catalog = catalog
        self.settings = settings
        self.offset: int | None = None

    # ── транспорт ──────────────────────────────────────────────
    def poll(self, timeout: int = 25) -> int:
        """Один long-poll запрос; возвращает число обработанных апдейтов."""
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self.api.call("getUpdates", **params) or []
        for u in updates:
            self.offset = u["update_id"] + 1
            try:
                self.handle(u)
            except Exception:
                log.exception("update %s failed", u.get("update_id"))
        return len(updates)

    def reply(self, chat_id, text: str, markup: dict | None = None):
        return notify.send_telegram(text, reply_markup=markup, chat_id=str(chat_id))

    def _authorized(self, chat_id) -> bool:
        return bool(self.settings.telegram_chat_id) and str(chat_id) == str(self.settings.telegram_chat_id)

    # ── маршрутизация ──────────────────────────────────────────
    def handle(self, update: dict) -> None:
        if cq := update.get("callback_query"):
            chat_id = cq["message"]["chat"]["id"]
            self.api.call("answerCallbackQuery", callback_query_id=cq["id"])
            if self._authorized(chat_id):
                self.on_button(chat_id, cq["message"]["message_id"], cq.get("data", ""))
            return
        msg = update.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        text = msg.get("text") or ""
        if chat_id is None:
            return
        if not self._authorized(chat_id):
            if text.startswith("/start"):
                # помогает при первой настройке: показываем chat_id, ничего больше не делаем
                self.reply(chat_id, f"Ваш chat_id: {chat_id}\nУкажите его в .env как TELEGRAM_CHAT_ID и перезапустите агент.")
            return
        self.on_command(chat_id, text)

    # ── кнопки ─────────────────────────────────────────────────
    def on_button(self, chat_id, message_id: int, data: str) -> None:
        action, _, raw_id = data.partition(":")
        if not raw_id.isdigit():
            return
        with self.session_factory() as session:
            job = session.get(Job, int(raw_id))
            if not job:
                self.reply(chat_id, f"Заказ #{raw_id} не найден")
                return
            try:
                if action == "draft":
                    self._draft(session, chat_id, job)
                elif action == "won":
                    self._won(session, chat_id, job, None)
                elif action in SIMPLE_MOVES:
                    crm.move(session, job, SIMPLE_MOVES[action], note="telegram")
                    session.commit()
                    self.reply(chat_id, f"#{job.id} → {job.stage.value}", notify.keyboard(job))
                else:
                    return
            except crm.TransitionError as e:
                self.reply(chat_id, f"#{job.id}: {e}. Сейчас этап: {job.stage.value}", notify.keyboard(job))
                return
            # убираем старые кнопки, чтобы не нажать устаревшее действие
            self.api.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                          reply_markup={"inline_keyboard": []})

    def _draft(self, session: Session, chat_id, job: Job) -> None:
        self.reply(chat_id, f"⏳ Пишу черновик для #{job.id}…")
        try:
            p = pipeline.draft(session, job, self.catalog, self.settings)
        except LLMError as e:
            self.reply(chat_id, f"Не получилось: {e}", notify.keyboard(job))
            return
        session.commit()
        self.reply(chat_id, p.text)  # отдельным сообщением — удобно скопировать
        meta = [f"#{job.id} · {job.platform} · {job.language}"]
        if p.price:
            meta.append(f"💵 ${p.price:.0f} — {p.price_note}")
        if p.questions:
            meta.append("❓ " + "\n❓ ".join(p.questions))
        if job.url:
            meta.append(job.url)
        self.reply(chat_id, "\n".join(meta), notify.keyboard(job))

    def _won(self, session: Session, chat_id, job: Job, amount: float | None) -> None:
        if amount is None:
            last = session.scalar(select(Proposal).where(Proposal.job_id == job.id).order_by(Proposal.id.desc()))
            amount = last.price if last and last.price else None
        crm.move(session, job, Stage.WON, note="telegram", contract_value=amount)
        session.commit()
        hint = "" if amount else f"\nСумма не указана — /won {job.id} <сумма>"
        self.reply(chat_id, f"🤝 #{job.id} контракт" + (f" на ${amount:.0f}" if amount else "") + hint
                   + (f"\nЕсли сумма другая: /won {job.id} <сумма>" if amount else ""), notify.keyboard(job))

    # ── команды ────────────────────────────────────────────────
    def on_command(self, chat_id, text: str) -> None:
        first, _, rest = text.partition("\n")
        parts = first.split()
        cmd = parts[0].split("@")[0].lower() if parts else ""
        args = parts[1:]

        if cmd in ("/start", "/help"):
            self.reply(chat_id, HELP)
        elif cmd == "/jobs":
            self.cmd_jobs(chat_id)
        elif cmd == "/job" and args and args[0].lstrip("#").isdigit():
            with self.session_factory() as s:
                job = s.get(Job, int(args[0].lstrip("#")))
                if job:
                    self.reply(chat_id, notify.job_card(job), notify.keyboard(job))
                else:
                    self.reply(chat_id, "Не найден")
        elif cmd == "/add":
            self.cmd_add(chat_id, args, rest)
        elif cmd == "/won" and len(args) == 2 and args[0].lstrip("#").isdigit():
            self.cmd_won(chat_id, int(args[0].lstrip("#")), args[1])
        elif cmd == "/collect":
            self.reply(chat_id, "⏳ Собираю…")
            with self.session_factory() as s:
                st = pipeline.run_collection(s, self.catalog, self.settings, use_llm=self.settings.use_llm_scoring)
            self.reply(chat_id, f"Получено {st['fetched']}, новых {st['new']}, подходящих {st['qualified']}"
                       + (f"\nОшибки: {'; '.join(st['errors'])}" if st["errors"] else ""))
        elif cmd == "/report":
            days = int(args[0]) if args and args[0].isdigit() else 7
            with self.session_factory() as s:
                self.reply(chat_id, reports.format_text(reports.summary(s, days)))
        else:
            self.reply(chat_id, "Не понял команду.\n\n" + HELP)

    def cmd_jobs(self, chat_id) -> None:
        with self.session_factory() as s:
            jobs = s.scalars(select(Job).where(Job.stage.in_([Stage.QUALIFIED, Stage.DRAFTED]))
                             .order_by(Job.score.desc()).limit(10)).all()
            if not jobs:
                self.reply(chat_id, "Нет заказов, ждущих решения.")
            for job in jobs:
                self.reply(chat_id, notify.job_card(job), notify.keyboard(job))

    def cmd_add(self, chat_id, args: list[str], body: str) -> None:
        platforms = ", ".join(self.catalog.platforms)
        if not args or args[0] not in self.catalog.platforms or not body.strip():
            self.reply(chat_id, f"Формат:\n/add upwork\n<текст заказа со следующей строки>\n\nПлатформы: {platforms}")
            return
        m = URL_RE.search(body)
        url = m.group(0) if m else ""
        text = URL_RE.sub("", body).strip() if m else body
        with self.session_factory() as s:
            new = pipeline.ingest(s, [parse_pasted(args[0], text, url)])
            if not new:
                self.reply(chat_id, "Этот заказ уже есть.")
                return
            job = new[0]
            # score_and_route сам пришлёт карточку, если заказ прошёл порог
            pipeline.score_and_route(s, job, self.catalog, self.settings, use_llm=self.settings.use_llm_scoring)
            s.commit()
            if job.stage != Stage.QUALIFIED:
                self.reply(chat_id, notify.job_card(job) + "\n\nНиже порога — пропущен. Вернуть можно кнопкой.",
                           notify.keyboard(job))

    def cmd_won(self, chat_id, job_id: int, raw_amount: str) -> None:
        try:
            amount = float(raw_amount.replace(",", ".").lstrip("$"))
        except ValueError:
            self.reply(chat_id, "Сумма должна быть числом: /won 12 450")
            return
        with self.session_factory() as s:
            job = s.get(Job, job_id)
            if not job:
                self.reply(chat_id, "Не найден")
                return
            if job.stage in (Stage.WON, Stage.DELIVERED, Stage.REVIEWED):
                job.contract_value = amount  # исправление суммы уже закрытого контракта
                s.commit()
                self.reply(chat_id, f"#{job.id}: сумма контракта ${amount:.0f}")
                return
            try:
                self._won(s, chat_id, job, amount)
            except crm.TransitionError as e:
                self.reply(chat_id, f"#{job.id}: {e}. Сейчас этап: {job.stage.value}", notify.keyboard(job))
