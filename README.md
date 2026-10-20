# Freelance Agent

Полуавтономный помощник: находит заказы по статистике, научному редактированию и оформлению,
оценивает их, считает цену и готовит черновик отклика на языке заказа (en / pl / ru / ua).
**Отправляет отклик всегда владелец.**

## Быстрый старт
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env          # ANTHROPIC_API_KEY, токены Telegram/Freelancehunt/Freelancer
.venv/bin/pytest -q           # тесты (без сети и API)
.venv/bin/fa serve            # API + документация: http://127.0.0.1:8000/docs
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

## Ежедневная работа
1. `fa collect` (или cron каждые 30 мин) → квалифицированные заказы приходят в Telegram.
2. Заказ из Upwork/LinkedIn-алерта: `POST /jobs/import {"platform": "upwork", "text": "...", "url": "..."}`.
3. `POST /jobs/{id}/draft` → черновик + цена + вопросы клиенту → правите и отправляете сами.
4. `POST /jobs/{id}/stage {"stage": "sent"}` … `{"stage": "won", "contract_value": 450}`.
5. `fa report --telegram` — сводка.

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
- Интеграция с ClickUp, кнопки в Telegram-боте (одобрить/пропустить), планировщик.
- Переход на PostgreSQL — достаточно сменить `DATABASE_URL`.
