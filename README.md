# Freelance Agent

Полуавтономный помощник: находит заказы по статистике, научному редактированию и оформлению,
оценивает их, считает цену и готовит черновик отклика на языке заказа (en / pl / ru / ua).
**Отправляет отклик всегда владелец.**

👉 **Пошаговая инструкция: [USAGE.md](USAGE.md)**

## Быстрый старт
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env          # ANTHROPIC_API_KEY, токены Telegram/Freelancehunt/Freelancer
.venv/bin/pytest -q           # тесты (без сети и API)
.venv/bin/fa run              # агент 24/7: Telegram-бот + сбор каждые 30 мин + отчёт в 20:00
.venv/bin/fa serve            # (опционально) HTTP API + документация: http://127.0.0.1:8000/docs
```

## Модули ТЗ
| Модуль | Файл | Статус |
|---|---|---|
| М1 Профили | `agent/profiles.py`, `profiles/master.yaml`, `config/platforms.yaml` | генератор готов; мастер-профиль ждёт данных |
| М2 Сбор заказов | `agent/collectors/` | Freelancehunt API, Freelancer API, RSS (Useme), вставка текста/e-mail-алертов (Upwork, Kolabtree, LinkedIn) |
| М3 Скоринг | `agent/scoring.py` | правила 0–100 (соответствие, бюджет, клиент, конкуренция, язык, red flags) + опционально Claude Haiku |
| М4 Отклики | `agent/proposals.py` | Claude Sonnet, язык заказа, лимиты платформы, только факты из профиля |
| М5 Цены | `agent/pricing.py` | за проект / час / страницу / 1000 слов, срочность, бюджет клиента, валюты, комиссия |
| М6 CRM | `agent/crm.py`, `agent/db.py` | воронка new → qualified → drafted → sent → replied → won → delivered → reviewed |
| М7 Отчёты | `agent/reports.py` | конверсия, выручка vs $10K к 11.12, отзывы, разбивка по платформам; `fa report --telegram` |

## Telegram и расписание
`agent/bot.py` — кнопки воронки под каждой карточкой и команды `/jobs /add /won /collect /report`;
бот отвечает только на `TELEGRAM_CHAT_ID`. `agent/scheduler.py` — сбор каждые `COLLECT_INTERVAL_MIN`
минут и ежедневный отчёт в `REPORT_TIME`. Для сервера: `deploy/freelance-agent.service` (systemd).

## Профили
```bash
fa profile upwork en   # тексты полей с учётом лимитов + список skills
fa profile useme pl
```
Пока в `profiles/master.yaml` есть `[плейсхолдеры]`, они остаются в текстах — генератор не выдумывает факты.

## Что заполнить
- `profiles/master.yaml` — образование, опыт, публикации, кейсы.
- `config/services.yaml` → `price_usd` — сейчас ориентиры-заглушки.
- `config/platforms.yaml` → `useme.feeds` — RSS-ленты категорий.
- `.env` — ключи.

## Пока не сделано
- Gmail API (автоматическое чтение писем-алертов) — сейчас текст вставляется через `/jobs/import`.
- Интеграция с ClickUp.
- Переход на PostgreSQL — достаточно сменить `DATABASE_URL`.
