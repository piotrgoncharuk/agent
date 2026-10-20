"""Расписание для `fa run`: сбор каждые N минут, ежедневный отчёт, опрос Telegram-бота."""
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import notify, pipeline, reports
from .bot import Bot
from .catalog import Catalog
from .settings import Settings

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, session_factory, catalog: Catalog, settings: Settings):
        self.session_factory = session_factory
        self.catalog = catalog
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self.next_collect: datetime | None = None   # None → собрать сразу при старте
        self.last_report_date = None

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def tick(self, now: datetime | None = None) -> list[str]:
        """Запускает всё, что пора запустить; возвращает имена выполненных задач."""
        now = now or self.now()
        done = []
        if self.next_collect is None or now >= self.next_collect:
            self.next_collect = now + timedelta(minutes=self.settings.collect_interval_min)
            self._safe("collect", self.collect)
            done.append("collect")
        if self._report_due(now):
            self.last_report_date = now.date()
            self._safe("report", self.report)
            done.append("report")
        return done

    def _report_due(self, now: datetime) -> bool:
        if not self.settings.report_time:
            return False
        hh, mm = map(int, self.settings.report_time.split(":"))
        if self.last_report_date is None:
            # при старте после времени отчёта не шлём вчерашний/сегодняшний повторно
            self.last_report_date = now.date() if (now.hour, now.minute) >= (hh, mm) else now.date() - timedelta(days=1)
        return now.date() > self.last_report_date and (now.hour, now.minute) >= (hh, mm)

    def collect(self) -> None:
        with self.session_factory() as s:
            st = pipeline.run_collection(s, self.catalog, self.settings, use_llm=self.settings.use_llm_scoring)
        log.info("collect: %s", st)
        if st["errors"]:
            notify.send_telegram("⚠️ Ошибки сбора: " + "; ".join(st["errors"]))

    def report(self) -> None:
        with self.session_factory() as s:
            notify.send_telegram(reports.format_text(reports.summary(s, days=1)))

    @staticmethod
    def _safe(name: str, fn) -> None:
        try:
            fn()
        except Exception:
            log.exception("scheduled task %s failed", name)


def run_forever(session_factory, catalog: Catalog, settings: Settings) -> None:
    """Главный цикл: long-poll Telegram (до 25 с) между проверками расписания."""
    sched = Scheduler(session_factory, catalog, settings)
    api = notify.get_api()
    bot = Bot(api, session_factory, catalog, settings) if api else None
    if not bot:
        log.warning("TELEGRAM_BOT_TOKEN не задан — работаю без бота, только сбор по расписанию")
    elif not settings.telegram_chat_id:
        log.warning("TELEGRAM_CHAT_ID не задан — напишите боту /start, он пришлёт ваш chat_id")
    log.info("агент запущен: сбор каждые %s мин, отчёт в %s (%s)",
             settings.collect_interval_min, settings.report_time or "—", settings.timezone)
    backoff = 1
    while True:
        sched.tick()
        if not bot:
            time.sleep(30)
            continue
        try:
            bot.poll(timeout=25)
            backoff = 1
        except Exception:
            log.exception("telegram poll failed; retry in %ss", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
