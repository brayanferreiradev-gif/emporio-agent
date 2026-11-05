"""Terminal chat: ``python -m emporio``."""
from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from . import config
from .agent import Agent
from .data import load_store
from .session import Session

BANNER = """\
🎸 Empório da Música — atendimento virtual (Dó)
   Digite sua mensagem. Comandos: /nova (limpa a conversa), /sair
"""


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stdin):
        stream.reconfigure(encoding="utf-8")
    load_dotenv(config.ROOT / ".env")

    ap = argparse.ArgumentParser(prog="emporio", description="Empório da Música support agent")
    ap.add_argument("--session", default="default", help="conversation id; history is saved in var/sessions/<id>.json")
    ap.add_argument("--new", action="store_true", help="start the session from scratch")
    ap.add_argument("--verbose", action="store_true", help="print the tool calls the agent makes")
    ap.add_argument("--now", help="simulate current date/time, e.g. 2026-03-23T10:30")
    args = ap.parse_args(argv)

    if args.now:
        os.environ["EMPORIO_NOW"] = args.now
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("Missing GEMINI_API_KEY. Copy .env.example to .env and add your key "
              "(free at https://aistudio.google.com/apikey).", file=sys.stderr)
        return 1

    session = Session.load(args.session)
    if args.new:
        session.reset()
    agent = Agent(load_store(), session)

    print(BANNER)
    if session.history:
        print(f"(conversa retomada: {len(session.history) // 2} mensagens anteriores)\n")
    while True:
        try:
            user = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        if user.lower() in ("/sair", "/exit", "sair"):
            return 0
        if user.lower() == "/nova":
            session.reset()
            print("(nova conversa)\n")
            continue
        try:
            turn = agent.reply(user)
        except Exception as e:  # network/quota problems should not kill the chat
            print(f"[erro ao falar com o modelo: {type(e).__name__}] Tente de novo em instantes.\n")
            continue
        if args.verbose:
            for c in turn.tool_calls:
                print(f"  ↳ {c['tool']}({json.dumps(c['args'], ensure_ascii=False)})")
        print(f"\nDó: {turn.reply}\n")


if __name__ == "__main__":
    raise SystemExit(main())
