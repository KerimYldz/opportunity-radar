"""Command line entry point: `radar run | test-notify | chat-id | import | list | stats | status`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

from . import config
from .digest import maybe_send_digest
from .inbox import process_inbox
from .models import RawPost
from .notifier import TelegramError, TelegramNotifier, local_time
from .pipeline import Pipeline, RunReport
from .sources import build_collectors, collect_all
from .storage import STATUSES, Store

log = logging.getLogger("opportunity_radar")


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _notifier(required: bool = False) -> TelegramNotifier | None:
    secrets = config.load_secrets()
    if secrets.telegram_configured:
        return TelegramNotifier(secrets.telegram_token, secrets.telegram_chat_id)
    msg = "Telegram is not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env or Actions secrets)."
    if required:
        sys.exit(msg)
    log.warning(msg + " Leads are stored and stay pending.")
    return None


def _print_report(report: RunReport) -> None:
    print(json.dumps(report.__dict__, indent=2))


def cmd_run(args) -> int:
    settings = config.load_settings(args.config)
    store = Store(config.db_path())
    started = datetime.now(timezone.utc)
    posts, errors = collect_all(build_collectors(settings))
    notifier = None if args.dry_run else _notifier()
    pipeline = Pipeline(settings, store, notifier)
    report = pipeline.run(posts, dry_run=args.dry_run)
    report.errors = errors + report.errors
    # After the collection run, so shared posts never affect cold-start detection.
    if notifier and settings.get("telegram_inbox", {}).get("enabled", True):
        try:
            inbox = process_inbox(notifier, pipeline, notifier.chat_id)
            log.info("telegram inbox: %d received, %d analyzed, %d ignored", inbox.received, inbox.analyzed, inbox.ignored)
        except TelegramError as exc:
            report.errors.append(f"telegram inbox: {exc}")
        try:
            if maybe_send_digest(settings, store, notifier):
                log.info("daily digest sent")
        except TelegramError as exc:
            report.errors.append(f"daily digest: {exc}")
    store.log_run(started, report.fetched, report.new, report.notified, report.errors)
    store.close()
    _print_report(report)
    # Fail the job only when nothing could be fetched at all.
    return 1 if report.fetched == 0 and errors else 0


def cmd_test_notify(args) -> int:
    notifier = _notifier(required=True)
    try:
        notifier.send(
            "<b>OPPORTUNITY RADAR — TEST</b>\n"
            "This is a test notification. If you can read it, alerts are configured correctly.\n"
            f"Sent at {local_time(datetime.now(timezone.utc))}"
        )
    except TelegramError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    print("Test notification sent.")
    return 0


def cmd_chat_id(args) -> int:
    secrets = config.load_secrets()
    if not secrets.telegram_token:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env first, then send any message to your bot.")
    updates = TelegramNotifier(secrets.telegram_token, "").get_updates()
    chats = {(u.get("message") or {}).get("chat", {}).get("id"): (u.get("message") or {}).get("chat", {}) for u in updates}
    chats.pop(None, None)
    if not chats:
        print("No messages found. Send /start to your bot in Telegram, then run this again.")
        return 1
    for cid, chat in chats.items():
        print(f"chat id: {cid}  ({chat.get('first_name') or chat.get('title') or ''})")
    print("Put it in .env as TELEGRAM_CHAT_ID=...")
    return 0


def _write_env(values: dict[str, str]) -> None:
    path = config.PROJECT_ROOT / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)


def _push_github_secrets(values: dict[str, str]) -> bool:
    import shutil
    import subprocess

    if not shutil.which("gh"):
        return False
    ok = True
    for name, value in values.items():
        # Value goes through stdin, never through argv or logs.
        res = subprocess.run(["gh", "secret", "set", name], input=value, text=True,
                             cwd=config.PROJECT_ROOT, capture_output=True)
        if res.returncode != 0:
            print(f"  could not set GitHub secret {name}: {res.stderr.strip()[:200]}")
            ok = False
    return ok


def cmd_setup_telegram(args) -> int:
    import getpass
    import time

    print("\nTelegram setup\n"
          "1. On your phone open Telegram, search for @BotFather and start a chat.\n"
          "2. Send /newbot, pick any name, then a username ending in 'bot'.\n"
          "3. BotFather replies with a token like 123456:ABC-xyz… — copy it.\n")
    token = getpass.getpass("Paste the token here (it stays hidden) and press Enter: ").strip()
    if not token:
        print("No token entered.")
        return 1
    probe = TelegramNotifier(token, "")
    try:
        me = probe.get_me()
    except TelegramError as exc:
        print(f"That token did not work: {exc}")
        return 1
    username = me.get("username", "")
    print(f"\nToken OK — your bot is @{username}.")
    print(f"4. On your phone open https://t.me/{username} and tap START (or send any message).")
    print("   Waiting up to 5 minutes…")
    chat_id, last_update = None, None
    deadline = time.time() + 300
    while time.time() < deadline and chat_id is None:
        for upd in probe.get_updates():
            last_update = upd["update_id"]
            chat = (upd.get("message") or {}).get("chat") or {}
            if chat.get("type") == "private":
                chat_id = str(chat["id"])
        if chat_id is None:
            time.sleep(3)
    if chat_id is None:
        print("No message arrived. Run this command again and tap START in the bot chat.")
        return 1
    if last_update is not None:
        probe.get_updates(offset=last_update + 1)  # mark the setup messages as read
    values = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id}
    _write_env(values)
    print("Saved to .env (readable only by you).")
    TelegramNotifier(token, chat_id).send(
        "<b>OPPORTUNITY RADAR</b>\nSetup complete. New leads will arrive here.\n\n"
        "To check a Facebook or Nextdoor post: send me its link and its text in one message."
    )
    print("Sent a test message — check your phone.")
    if _push_github_secrets(values):
        print("Also stored both values as GitHub Actions secrets for this repo.")
    else:
        print("GitHub secrets not set (connect GitHub first, then run: ./radar push-secrets).")
    return 0


def cmd_push_secrets(args) -> int:
    secrets = config.load_secrets()
    if not secrets.telegram_configured:
        sys.exit("Run ./radar setup-telegram first.")
    values = {"TELEGRAM_BOT_TOKEN": secrets.telegram_token, "TELEGRAM_CHAT_ID": secrets.telegram_chat_id}
    if not _push_github_secrets(values):
        return 1
    print("GitHub Actions secrets updated.")
    return 0


def cmd_inbox(args) -> int:
    settings = config.load_settings(args.config)
    notifier = _notifier(required=True)
    store = Store(config.db_path())
    report = process_inbox(notifier, Pipeline(settings, store, notifier), notifier.chat_id)
    store.close()
    print(json.dumps(report.__dict__, indent=2))
    return 0


def cmd_import(args) -> int:
    """Manual import for platforms we must not scrape (Facebook, Nextdoor, ...)."""
    settings = config.load_settings(args.config)
    text = args.text if args.text != "-" else sys.stdin.read()
    published = datetime.fromisoformat(args.published).astimezone(timezone.utc) if args.published else None
    body = text if not args.screenshot_note else f"{text}\n[screenshot description] {args.screenshot_note}"
    post = RawPost(
        source=f"{args.platform} (manual)",
        source_detail="manual import",
        url=args.url,
        title=args.title or text.strip().splitlines()[0][:120],
        body=body,
        published_at=published,
        date_verified=False,  # you typed the date; we cannot verify it
    )
    store = Store(config.db_path())
    pipeline = Pipeline(settings, store, _notifier() if args.notify else None)
    report = RunReport(fetched=1)
    pipeline.ingest([post], report)
    if args.notify:
        pipeline.notify(report)
    from .dedup import lead_id
    row = store.conn.execute("SELECT analysis_json, notify_state FROM leads WHERE id = ?", (lead_id(post.url),)).fetchone()
    print(json.dumps({"report": report.__dict__, "notify_state": row["notify_state"], "analysis": json.loads(row["analysis_json"])}, indent=2))
    store.close()
    return 0


def cmd_list(args) -> int:
    store = Store(config.db_path())
    for r in store.list_leads(limit=args.limit, only_passed=not args.all):
        print(f"[{r['priority']:>3}] suit={r['suitability']:>3} scam={r['scam_score']:>3} {r['notify_state']:<10} "
              f"{r['status']:<10} {r['id']} {r['title'][:70]}\n      {r['url']}")
    store.close()
    return 0


def cmd_stats(args) -> int:
    store = Store(config.db_path())
    print(json.dumps(store.stats(), indent=2))
    store.close()
    return 0


def cmd_status(args) -> int:
    store = Store(config.db_path())
    store.set_status(args.lead_id, args.status)
    store.close()
    print(f"{args.lead_id} -> {args.status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(prog="radar", description="Opportunity Radar")
    p.add_argument("--config", help="path to settings.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="collect, analyze, store and notify")
    r.add_argument("--dry-run", action="store_true", help="store leads but do not send Telegram messages")
    r.set_defaults(func=cmd_run)

    sub.add_parser("test-notify", help="send a test Telegram message").set_defaults(func=cmd_test_notify)
    sub.add_parser("chat-id", help="print chat ids that messaged your bot").set_defaults(func=cmd_chat_id)
    sub.add_parser("setup-telegram", help="guided bot setup: token, chat id, test message").set_defaults(func=cmd_setup_telegram)
    sub.add_parser("push-secrets", help="copy Telegram values from .env to GitHub Actions secrets").set_defaults(func=cmd_push_secrets)
    sub.add_parser("inbox", help="analyze posts you sent to the bot now").set_defaults(func=cmd_inbox)

    i = sub.add_parser("import", help="manually import a post (Facebook, Nextdoor, ...)")
    i.add_argument("--url", required=True)
    i.add_argument("--text", required=True, help="post text, or '-' to read stdin")
    i.add_argument("--platform", required=True)
    i.add_argument("--title")
    i.add_argument("--published", help="ISO datetime if shown on the post (stored as unverified)")
    i.add_argument("--screenshot-note")
    i.add_argument("--notify", action="store_true")
    i.set_defaults(func=cmd_import)

    ls = sub.add_parser("list", help="show top leads")
    ls.add_argument("--limit", type=int, default=20)
    ls.add_argument("--all", action="store_true", help="include rejected and duplicates")
    ls.set_defaults(func=cmd_list)

    sub.add_parser("stats").set_defaults(func=cmd_stats)

    st = sub.add_parser("status", help="set manual tracking status of a lead")
    st.add_argument("lead_id")
    st.add_argument("status", choices=STATUSES)
    st.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
