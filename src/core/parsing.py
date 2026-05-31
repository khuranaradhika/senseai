"""
Safe structured-output layer.

LLMs return JSON-ish text that may be wrapped in markdown fences, prefixed with
prose, or subtly malformed. A bare `json.loads(raw)` (as the legacy agents did)
crashes the whole run on the first drift. This module:

  1. extracts the JSON payload from messy text,
  2. validates it against a Pydantic model,
  3. on failure, optionally *reprompts once* with the validation error,
  4. and raises a typed error if it still can't parse — so the caller decides
     the fallback instead of the process dying.
"""
import json
from typing import Callable, Optional, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class StructuredParseError(ValueError):
    """Raised when LLM output cannot be coerced into the target model."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def extract_json(raw: str) -> str:
    """Pull the JSON object/array out of fenced or prose-wrapped LLM text."""
    if raw is None:
        raise StructuredParseError("empty LLM output", raw="")
    text = raw.strip()

    # Strip a leading ```json / ``` fence and trailing ```
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()

    # Isolate the outermost JSON span in case prose surrounds it.
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    ends = [i for i in (text.rfind("}"), text.rfind("]")) if i != -1]
    if starts and ends:
        text = text[min(starts): max(ends) + 1]
    return text.strip()


def _load(raw: str, model: type[T]) -> T:
    cleaned = extract_json(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise StructuredParseError(f"invalid JSON: {e}", raw=raw) from e
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise StructuredParseError(f"schema validation failed: {e}", raw=raw) from e


def parse_structured(
    raw: str,
    model: type[T],
    *,
    reprompt: Optional[Callable[[str], str]] = None,
) -> T:
    """
    Parse `raw` into `model`. On failure, call `reprompt(error_message)` once to
    get a corrected response and try again. A second failure raises
    StructuredParseError.

    `reprompt` is supplied by the agent (it re-invokes the LLM with the error
    appended), keeping this module independent of the LLM client.
    """
    try:
        return _load(raw, model)
    except StructuredParseError as first_err:
        if reprompt is None:
            raise
        corrected = reprompt(str(first_err))
        return _load(corrected, model)  # second failure propagates to caller
