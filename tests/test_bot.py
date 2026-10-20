from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agent import notify, scheduler
from agent.bot import Bot
from agent.db import Job, Stage, make_session_factory
from agent.proposals import ProposalDraft
from agent.settings import Settings

CHAT = "111"


class FakeAPI:
    def __init__(self):
        self.calls = []

    def call(self, method, **params):
        self.calls.append((method, params))
        return {"message_id": len(self.calls)} if method == "sendMessage" else True

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]


@pytest.fixture
def env(monkeypatch, catalog):
    settings = Settings(telegram_bot_token="t", telegram_chat_id=CHAT)
    api = FakeAPI()
    monkeypatch.setattr(notify, "get_api", lambda: api)
    monkeypatch.setattr(notify, "get_settings", lambda: settings)
    draft = ProposalDraft(text="Hello, I will run the meta-analysis…", questions=["How many studies?"],
                          estimated_days=5, decline=False, decline_reason="")
    fake_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **kw: SimpleNamespace(stop_reason="end_turn", stop_details=None, parsed_output=draft))))
    monkeypatch.setattr("agent.llm.get_client", lambda: fake_client)
    factory = make_session_factory("sqlite://")
    return SimpleNamespace(api=api, bot=Bot(api, factory, catalog, settings), factory=factory, settings=settings)


def msg(text, chat=CHAT):
    return {"update_id": 1, "message": {"chat": {"id": int(chat)}, "text": text}}


def press(data, chat=CHAT):
    return {"update_id": 2, "callback_query": {"id": "cb", "data": data,
                                               "message": {"chat": {"id": int(chat)}, "message_id": 7}}}


def buttons(params):
    return [b["callback_data"] for row in params.get("reply_markup", {}).get("inline_keyboard", []) for b in row]


ADD = ("/add upwork\nMeta-analysis of RCTs with forest plots\nBudget: $900\n"
       "Systematic review per PRISMA, risk of bias, funnel plot. https://www.upwork.com/jobs/~01abc")


def test_stranger_gets_only_chat_id(env):
    env.bot.handle(msg("/start", chat="999"))
    env.bot.handle(msg("/jobs", chat="999"))
    sent = env.api.sent()
    assert len(sent) == 1 and "999" in sent[0]["text"] and sent[0]["chat_id"] == "999"


def test_full_funnel_via_buttons(env):
    env.bot.handle(msg(ADD))
    card = env.api.sent()[-1]
    assert "Meta-analysis" in card["text"] and "upwork.com/jobs" in card["text"]
    assert buttons(card) == ["draft:1", "skip:1"]

    env.bot.handle(press("draft:1"))
    texts = [p["text"] for p in env.api.sent()]
    assert "Hello, I will run the meta-analysis…" in texts
    assert "How many studies?" in env.api.sent()[-1]["text"]
    assert buttons(env.api.sent()[-1]) == ["sent:1", "draft:1", "skip:1"]
    assert ("editMessageReplyMarkup", {"chat_id": int(CHAT), "message_id": 7,
                                       "reply_markup": {"inline_keyboard": []}}) in env.api.calls

    for action in ("sent", "replied", "won", "delivered", "reviewed"):
        env.bot.handle(press(f"{action}:1"))
    with env.factory() as s:
        job = s.get(Job, 1)
        assert job.stage == Stage.REVIEWED
        assert job.contract_value == 1200  # цена из последнего черновика (бюджет $900 < 80% от $1200)


def test_stale_button_is_rejected(env):
    env.bot.handle(msg(ADD))
    env.bot.handle(press("sent:1"))  # нельзя отправить без черновика
    assert "не разрешён" in env.api.sent()[-1]["text"]


def test_won_command_and_amount_fix(env):
    env.bot.handle(msg(ADD))
    env.bot.handle(press("draft:1"))
    env.bot.handle(press("sent:1"))
    env.bot.handle(msg("/won 1 750"))
    env.bot.handle(msg("/won 1 800"))
    with env.factory() as s:
        job = s.get(Job, 1)
        assert job.stage == Stage.WON and job.contract_value == 800


def test_add_offtopic_is_skipped_but_restorable(env):
    env.bot.handle(msg("/add upwork\nBuild a Shopify store\nNeed e-commerce site"))
    last = env.api.sent()[-1]
    assert "пропущен" in last["text"] and buttons(last) == ["restore:1"]


def test_scheduler_ticks(env, monkeypatch):
    runs = []
    monkeypatch.setattr(scheduler.Scheduler, "collect", lambda self: runs.append("c"))
    monkeypatch.setattr(scheduler.Scheduler, "report", lambda self: runs.append("r"))
    tz = ZoneInfo("Europe/Warsaw")
    sch = scheduler.Scheduler(env.factory, None, Settings(collect_interval_min=30, report_time="20:00"))
    assert sch.tick(datetime(2026, 10, 21, 19, 50, tzinfo=tz)) == ["collect"]
    assert sch.tick(datetime(2026, 10, 21, 19, 55, tzinfo=tz)) == []
    assert sch.tick(datetime(2026, 10, 21, 20, 1, tzinfo=tz)) == ["report"]
    assert sch.tick(datetime(2026, 10, 21, 20, 21, tzinfo=tz)) == ["collect"]
    assert sch.tick(datetime(2026, 10, 21, 22, 0, tzinfo=tz)) == ["collect"]  # отчёт раз в день
    assert sch.tick(datetime(2026, 10, 22, 20, 0, tzinfo=tz)) == ["collect", "report"]


def test_scheduler_start_after_report_time_skips_today(env, monkeypatch):
    monkeypatch.setattr(scheduler.Scheduler, "collect", lambda self: None)
    monkeypatch.setattr(scheduler.Scheduler, "report", lambda self: None)
    sch = scheduler.Scheduler(env.factory, None, Settings(report_time="20:00"))
    assert "report" not in sch.tick(datetime(2026, 10, 21, 23, 0, tzinfo=ZoneInfo("Europe/Warsaw")))


def test_split_text():
    parts = notify.split_text("abc\n" * 2000, limit=1000)
    assert all(len(p) <= 1000 for p in parts) and "".join(parts).count("abc") == 2000
