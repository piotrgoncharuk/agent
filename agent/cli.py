"""CLI: fa run | fa collect | fa report | fa profile upwork en | fa serve"""
import argparse
import json
import logging

from .catalog import get_catalog
from .db import make_session_factory
from .settings import get_settings


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="fa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="собрать и оценить заказы")
    c.add_argument("--llm", action="store_true", help="уточнять оценку через Claude")
    r = sub.add_parser("report", help="отчёт по воронке")
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--telegram", action="store_true")
    p = sub.add_parser("profile", help="сгенерировать тексты профиля")
    p.add_argument("platform")
    p.add_argument("language", choices=["en", "pl", "ru", "ua"])
    sub.add_parser("serve", help="запустить API на :8000")
    sub.add_parser("run", help="агент 24/7: Telegram-бот + сбор по расписанию + вечерний отчёт")
    args = ap.parse_args(argv)

    settings, catalog = get_settings(), get_catalog()
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("agent.api:app", host="127.0.0.1", port=8000)
        return
    if args.cmd == "run":
        from .scheduler import run_forever
        run_forever(make_session_factory(), catalog, settings)
        return
    if args.cmd == "profile":
        from .profiles import generate_profile
        out = generate_profile(args.platform, args.language, catalog, model=settings.model_writer)
        for f in out.fields:
            print(f"── {f.field} ({len(f.text)} симв.) ──\n{f.text}\n")
        print("skills:", ", ".join(out.keywords))
        return

    with make_session_factory()() as session:
        if args.cmd == "collect":
            from .pipeline import run_collection
            print(json.dumps(run_collection(session, catalog, settings, use_llm=args.llm), ensure_ascii=False, indent=2))
        elif args.cmd == "report":
            from . import reports
            text = reports.format_text(reports.summary(session, args.days))
            print(text)
            if args.telegram:
                from .notify import send_telegram
                send_telegram(text)


if __name__ == "__main__":
    main()
