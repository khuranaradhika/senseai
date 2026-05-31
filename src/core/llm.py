import os
import requests
import weave
from dotenv import load_dotenv

load_dotenv(override=True)

WANDB_API_KEY = os.getenv("WANDB_API_KEY")
WANDB_BASE_URL = "https://api.inference.wandb.ai/v1"#"https://api.wandb.ai/inference/v1"

# Two-tier model routing
FAST_MODEL = "deepseek/deepseek-v4-flash"       # specialists: cheap + fast
SMART_MODEL = "deepseek/deepseek-v4-0324"        # chair + compliance: best reasoning


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
    r = requests.post(
        f"{WANDB_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


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
def call_llm_structured(system: str, user: str, agent_name: str = "unknown", smart: bool = False) -> str:
    """LLM call expecting JSON. Strips markdown fences."""
    raw = call_llm(system=system, user=user, agent_name=agent_name, smart=smart)
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return clean.strip()