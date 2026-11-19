"""Metered real LLM calls with a conservative pre-call reservation and no silent fallback."""
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from .security import ROOT

load_dotenv(ROOT / ".env")

# Official DeepSeek pricing checked 2026-11-19; peak cache-miss input / output USD per million.
PRICING = {"source": "https://api-docs.deepseek.com/quick_start/pricing/", "checked": "2026-11-19",
           "model": "deepseek-flash", "input_per_million": .30, "output_per_million": 1.20,
           "basis": "conservative peak cache-miss rates; excludes cache/off-peak discounts"}


class Provider:
    def __init__(self, store):
        self.store = store
        key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_KEY") or os.getenv("deepseek_key")
        self.client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=60., max_retries=0)

    def call(self, rid, messages, tools=None):
        serialized = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False)
        if len(serialized.encode()) > 24000:
            raise ValueError("Prompt exceeds the bounded context budget")
        # UTF-8 bytes conservatively upper-bound tokenizer count for this text/tool payload.
        reserved = ((len(serialized.encode()) + 1024) * .30 + 1000 * 1.20) / 1e6
        call_id = self.store.reserve(rid, reserved, limit=5.)
        options = {"tools": tools, "parallel_tool_calls": False, "tool_choice": "required"} if tools else {"response_format": {"type": "json_object"}}
        result = self.client.chat.completions.create(model="deepseek-flash", messages=messages,
                   max_tokens=1000, temperature=0, extra_body={"thinking": {"type": "disabled"}}, **options)
        usage = result.usage.model_dump()
        cost = (usage["prompt_tokens"] * .30 + usage["completion_tokens"] * 1.20) / 1e6
        self.store.settle(call_id, {**usage, "model_returned": result.model, "pricing": PRICING}, cost)
        return result.choices[0].message
