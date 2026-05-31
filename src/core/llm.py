import os
import anthropic
import weave
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-20250514"


@weave.op()
def call_llm(system: str, user: str, agent_name: str = "unknown") -> str:
    """
    Base LLM call instrumented with Weave.
    Every agent call is traced with agent_name for observability.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


@weave.op()
def call_llm_structured(system: str, user: str, agent_name: str = "unknown") -> str:
    """
    LLM call expecting JSON output.
    Strips markdown fences before returning.
    """
    raw = call_llm(system=system, user=user, agent_name=agent_name)
    # Strip markdown fences if present
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])
    return clean.strip()
