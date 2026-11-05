"""The agent: a manual function-calling loop on top of the Gemini API.

Flow per customer message:
    history + message -> model -> (tool calls -> tool results -> model)* -> final text

Why a manual loop instead of the SDK's automatic function calling: we need every tool call
and result for tracing/--verbose and for the example transcripts, a hard cap on steps, and
safe handling of tool exceptions.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from . import config
from .data import Store
from .policies import PolicyIndex
from .prompts import build_system_prompt
from .session import Session
from .tools import Tools

MAX_STEPS = 6  # model <-> tool round trips per customer message
FALLBACK = "Desculpa, tive um probleminha aqui para te responder agora. Pode repetir sua pergunta? 🎸"


@dataclass
class Turn:
    reply: str
    tool_calls: list[dict] = field(default_factory=list)  # [{"tool", "args", "result"}]


class Agent:
    def __init__(self, store: Store, session: Session, client: genai.Client | None = None, policies: PolicyIndex | None = None):
        self.store, self.session = store, session
        # Reads GEMINI_API_KEY / GOOGLE_API_KEY. SDK-internal retries are capped at 1 attempt: we do our own
        # fallback across models, which recovers much faster than waiting on an overloaded one.
        self.client = client or genai.Client(http_options=types.HttpOptions(
            timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.tools = Tools(store, policies or PolicyIndex(), session)
        self._fns = {f.__name__: f for f in self.tools.as_functions()}

    # ------------------------------------------------------------------ model access
    def _context_notes(self) -> str:
        notes = [m["notes"] for m in self.session.window() if m.get("notes")]
        return " | ".join(notes[-4:])  # most recent lookups only

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=build_system_prompt(self.store, config.now(), self._context_notes()),
            tools=self.tools.as_functions(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.3,
            # "low" thinking is ~4x faster than default with the same answer quality on this task
            # (measured: 7s vs 30s for a catalogue question). Override with GEMINI_THINKING.
            thinking_config=types.ThinkingConfig(thinking_level=config.thinking_level()),
        )

    def _generate(self, contents: list[types.Content], cfg: types.GenerateContentConfig):
        """Call the model, retrying transient errors (free tier returns 429/503 under load)."""
        last: Exception | None = None
        for model in config.model_chain():
            for attempt in range(2):
                try:
                    return self.client.models.generate_content(model=model, contents=contents, config=cfg)
                except errors.APIError as e:
                    # 404 = model retired for this key, 429/5xx = quota or overload -> try the next one
                    if getattr(e, "code", None) not in (404, 429, 500, 503, 504):
                        raise
                    last = e
                    if getattr(e, "code", None) in (404, 429):
                        break  # retrying the same model will not help: quota/retired -> next model
                    time.sleep(1.5 * (attempt + 1))
                except httpx.HTTPError as e:  # timeouts, dropped connections: transient too
                    last = e
                    time.sleep(1.5 * (attempt + 1))
        raise last  # type: ignore[misc]

    def _run_tool(self, name: str, args: dict[str, Any]) -> dict:
        fn = self._fns.get(name)
        if fn is None:
            return {"error": f"Unknown tool '{name}'."}
        try:
            return fn(**args)
        except Exception as e:  # a bad tool call must not crash the conversation
            return {"error": f"Tool failed: {type(e).__name__}: {e}"}

    # ------------------------------------------------------------------ conversation
    def reply(self, user_text: str) -> Turn:
        contents = [types.Content(role=m["role"], parts=[types.Part(text=m["text"])]) for m in self.session.window()]
        contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        cfg, calls, text = self._config(), [], ""

        for _ in range(MAX_STEPS):
            resp = self._generate(contents, cfg)
            if not resp.candidates or not resp.candidates[0].content:
                break
            content = resp.candidates[0].content
            fcalls = [p.function_call for p in (content.parts or []) if p.function_call]
            if not fcalls:
                text = "".join(p.text for p in (content.parts or []) if p.text and not p.thought).strip()
                break
            contents.append(content)  # keep the model turn as-is (preserves thought signatures)
            results = []
            for fc in fcalls:
                args = dict(fc.args or {})
                result = self._run_tool(fc.name, args)
                calls.append({"tool": fc.name, "args": args, "result": result})
                results.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=results))

        # WhatsApp bold is *x*; the model sometimes slips into Markdown **x** despite the prompt.
        text = whatsapp_format(text) or FALLBACK
        self.session.add("user", user_text)
        self.session.add("model", text, notes=_memo(calls))
        self.session.save()
        return Turn(text, calls)


_LEAK_RE = re.compile(r"\s*\[(?:internal )?notes?\b[^\]]*\]", re.I)


def whatsapp_format(text: str) -> str:
    """Final clean-up of a reply: Markdown **bold** -> WhatsApp *bold*, and remove any internal-note
    markers the model might echo (they must never reach the customer)."""
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", _LEAK_RE.sub("", text)).strip()


def _memo(calls: list[dict]) -> str:
    """Compact internal notes of what the tools returned this turn (product ids, orders).

    The chat history only stores plain text, so without this the model forgets ids like
    'product 89' between turns and has to search again. Notes are sent back to the model
    but never shown to the customer.
    """
    products: dict[int, str] = {}
    orders: set[int] = set()

    def walk(node):
        if isinstance(node, dict):
            if "product_id" in node and "name" in node:
                products[node["product_id"]] = node["name"]
            if "order_id" in node and isinstance(node["order_id"], int) and "error" not in node:
                orders.add(node["order_id"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for c in calls:
        walk(c["result"])
    parts = []
    if products:
        parts.append("products mentioned: " + "; ".join(f"id {i} = {n}" for i, n in products.items()))
    if orders:
        parts.append("orders looked up (customer already verified): " + ", ".join(map(str, sorted(orders))))
    return " | ".join(parts)
