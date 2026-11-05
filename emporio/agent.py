"""The agent: a manual function-calling loop on top of the Gemini API.

Flow per customer message:
    history + message -> model -> (tool calls -> tool results -> model)* -> final text

Why a manual loop instead of the SDK's automatic function calling: we need every tool call
and result for tracing/--verbose and for the example transcripts, a hard cap on steps, and
safe handling of tool exceptions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

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
        self.client = client or genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY
        self.tools = Tools(store, policies or PolicyIndex(), session)
        self._fns = {f.__name__: f for f in self.tools.as_functions()}

    # ------------------------------------------------------------------ model access
    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=build_system_prompt(self.store, config.now()),
            tools=self.tools.as_functions(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.3,
        )

    def _generate(self, contents: list[types.Content], cfg: types.GenerateContentConfig):
        """Call the model, retrying transient errors (free tier returns 429/503 under load)."""
        for attempt in range(4):
            try:
                return self.client.models.generate_content(model=config.model_name(), contents=contents, config=cfg)
            except errors.APIError as e:
                transient = getattr(e, "code", None) in (429, 500, 503, 504)
                if not transient or attempt == 3:
                    raise
                time.sleep(2 ** attempt * 2)

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

        text = text or FALLBACK
        self.session.add("user", user_text)
        self.session.add("model", text)
        self.session.save()
        return Turn(text, calls)
