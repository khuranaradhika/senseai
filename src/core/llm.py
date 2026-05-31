import os
import time
from typing import TypeVar

import requests
import weave
from dotenv import load_dotenv
from pydantic import BaseModel

from src.core.config import CONFIG, FAST_MODEL, SMART_MODEL
from src.core.parsing import parse_structured

T = TypeVar("T", bound=BaseModel)

load_dotenv(override=True)

WANDB_API_KEY = os.getenv("WANDB_API_KEY")
WANDB_BASE_URL = "https://api.inference.wandb.ai/v1"


def _call(model: str, system: str, user: str) -> str:
    headers = {
        "Authorization": f"Bearer {WANDB_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 1000,
        "temperature": 0.3,
    }

    last_err: Exception | None = None
    for attempt in range(CONFIG.llm_max_retries):
        try:
            r = requests.post(
                f"{WANDB_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=CONFIG.llm_timeout_s,
            )
            # Retry transient server errors; surface 4xx immediately (won't fix itself).
            if r.status_code >= 500:
                r.raise_for_status()
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and status < 500:
                raise  # client error — retrying won't help
            last_err = e

        if attempt < CONFIG.llm_max_retries - 1:
            time.sleep(2 ** attempt)  # 1s, 2s, 4s exponential backoff

    raise RuntimeError(
        f"LLM call to {model} failed after {CONFIG.llm_max_retries} attempts: {last_err}"
    )


@weave.op()
def call_llm(system: str, user: str, agent_name: str = "unknown", smart: bool = False) -> str:
    """
    Two-tier LLM routing instrumented with Weave.
    smart=True → DeepSeek V4-Pro (Chair, Compliance)
    smart=False → DeepSeek V4-Flash (specialists)
    """
    model = SMART_MODEL if smart else FAST_MODEL
    return _call(model=model, system=system, user=user)


@weave.op()
def call_typed(
    system: str,
    user: str,
    schema: type[T],
    *,
    agent_name: str = "unknown",
    smart: bool = False,
) -> T:
    """
    LLM call validated into a Pydantic model. On a parse/validation failure it
    reprompts once with the error appended (see src/core/parsing), then raises a
    typed StructuredParseError if it still can't comply — so a single bad
    response never crashes the debate loop.
    """
    def _run(extra: str = "") -> str:
        return call_llm(system=system, user=user + extra, agent_name=agent_name, smart=smart)

    def _reprompt(err: str) -> str:
        return _run(
            f"\n\nYour previous response failed validation: {err}\n"
            "Return ONLY a valid JSON object matching the requested schema — no prose, no markdown."
        )

    return parse_structured(_run(), schema, reprompt=_reprompt)