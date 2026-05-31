# SenseAI — Learnings

Engineering learnings from building the committee — the bugs that mattered, the design
choices and why, and the failure modes that only showed up once it ran. Roughly in the
order they came up.

---

## 1. Config drift bites silently — verify model IDs against the live API
The first migration to W&B Inference used invented model IDs (`deepseek/deepseek-v4-flash`,
`…-v4-0324`) and the wrong base URL, so every call 404'd. The fix wasn't guessing — it was
hitting `GET /v1/models` to get the **exact** IDs (`deepseek-ai/DeepSeek-V4-Flash` / `-V4-Pro`).
**Lesson:** for any external API, enumerate the real identifiers; don't trust a plausible-looking
string (or an LLM's memory of one).

## 2. `.env` belongs in `.gitignore` *before* the first commit
The repo had `.env` committed (and pushed to a public remote) with live keys, even though
`.gitignore` listed it — because gitignore doesn't untrack already-tracked files. Rotation,
not deletion, is the real fix once a secret is public. **Lesson:** secrets hygiene is a
day-zero concern; `git rm --cached` + rotate, and assume anything pushed public is burned.

## 3. Env var names are an interface — match the vendor's
Alpaca calls 401'd because the code read `ALPACA_API_KEY` while `.env` used Alpaca's standard
`APCA_API_KEY_ID`. Then a second 404 from a doubled `/v2/v2/` because the base URL already
included `/v2`. **Lesson:** adopt the vendor's canonical env names, and **normalize** base URLs
defensively (strip trailing `/v2`, accept both name styles).

## 4. Guardrails must be enforced in code, not described in a prompt
`min_confidence_to_trade` was "configured," but it lived only in the compliance *prompt* — an
LLM could ignore it. The rebuild moved all hard limits into a pure `evaluate()` function
(confidence gate, market hours, position/portfolio caps, daily cap, conflicting position) that
runs as the final gate and that the LLMs cannot override. It immediately caught a BUY that had
been slipping through on a closed market. **Lesson:** anything that must always hold belongs in
deterministic code with tests — prompts *advise*, code *enforces*.

## 5. Fail safe, not open
When the broker is unreachable for guardrail inputs, the trade is **blocked**, not waved
through. **Lesson:** the default on missing safety information is "don't act."

## 6. Make LLM output non-fatal
Bare `json.loads(raw)` crashed a whole run on the first formatting drift. The `call_typed` path
(extract → Pydantic validate → **reprompt once** with the error → typed failure) turned a hard
crash into a recoverable, observable event. **Lesson:** treat model output as untrusted input —
validate, give it one structured chance to fix itself, and degrade typed.

## 7. "Advocate" agents don't track the data
The original Bull/Bear were prompted to *always* argue their side, so the vote was predetermined
and only the confidence number moved. Reframing them as **data-driven analysts with a lens**
(look hardest for the upside/downside, but vote honestly) made the votes actually reflect the
evidence. **Lesson:** if you want signal, don't hard-code the conclusion into the role.

## 8. More agents ≠ more signal; more *distinct data* does
The instinct to "add voters" is a trap when they all read the same one-line summary — you get
correlated echoes and higher cost. The win was giving the existing four **distinct inputs**
(fundamentals, sector relative-strength, macro regime, news) so each lens has something real to
reason over. **Lesson:** widen the information, not the headcount.

## 9. Duplicated data becomes an anchor
P/E was fed twice — in the price summary (context-free) *and* the fundamentals brief — and the
agents over-anchored on it as "overvalued." Removing it from the price line (leaving it once,
beside forward P/E + PEG) plus an explicit "don't over-index on one metric" instruction fixed
the bias. **Lesson:** repetition is implicit weighting; say important things once, in context.

## 10. Consensus-seeking breeds herding ("3 agree, the 4th folds")
Once three analysts aligned, the holdout capitulated — bandwagon, not analysis. Three sources of
pressure: the prompt valorized changing your mind, peers' votes were a visible scoreboard, and
the Chair was told to drive *convergence* and was fed the raw tally (which it echoed as "leans
3-1"). Fixes: tell analysts the **headcount is not evidence** and a well-reasoned minority beats
false consensus; make the Chair **protect dissent** (push the majority to rebut the minority,
never cite the count). **Lesson:** a debate optimized for agreement manufactures agreement —
design explicitly for productive disagreement, and expect (correctly) more tie-breaks.

## 11. Give the model a sense of "now"
Agents inferred the date from training data and treated undated prices as live. Injecting a
grounded `time_context()` (today's date + market open/closed) and stamping market data with an
`as_of` date made horizon reasoning honest — an intraday call now knows the market is closed and
the price is Friday's. **Lesson:** time-relative reasoning needs an explicit clock; never assume
the model knows what day it is.

## 12. One source of truth for thresholds
Scattered literals (and a stale `claude-sonnet` config left over from a provider migration) get
out of sync. Centralizing every limit + model tier in `config.py` (env-overridable) made the
system tunable without code edits and killed the drift. **Lesson:** constants that govern
behavior belong in one importable place.

## 13. Observability has to be coherent across entry points
Tracing (Weave) worked everywhere, but **metrics** only fired from the CLI, a stale duplicate
server (`api.py`) shadowed the real one on the same port with an outdated flow, and the
"evaluator" was imported but never called. Deleting the duplicate, logging W&B metrics from the
live server too, and replacing the dead scorer with a used `score_debate` made the story
consistent. **Lesson:** audit what's *actually* wired, not what's *named* — dead/duplicate code
is worse than missing code because it misleads.

## 14. Inputs are not ground truth — close the outcome loop
The market strip looked authoritative, but it's delayed third-party data with home-rolled
indicators, and nothing ever measured whether a decision was *right*. The decision journal
(persist entry price → score against forward price) is the start of real ground truth.
**Lesson:** distinguish inputs from outcomes; a system that never grades itself can't be called
robust no matter how clean the process looks.

## 15. Match the indicator to the convention
RSI used a simple moving average and read ~84 where charts showed ~79. Switching to Wilder's
smoothing made it comparable to what users actually see. **Lesson:** when you surface a standard
metric, compute it the standard way or it quietly misleads.

## 16. Robust *process* ≠ robust *system*
The harness became hard to crash, well-instrumented, and safety-gated — genuinely robust as
software. But with no track record, uncalibrated self-reported confidence, and hallucination
risk in the briefs, it is **not** a robust decision engine. **Lesson:** be precise about which
claim you're making; engineering robustness and predictive robustness are different axes.

---

### Recurring themes
- **Enforce in code, advise in prompts.**
- **Validate and ground everything the model says** (format, time, and — next — factual claims).
- **Design against the failure mode, not just for the happy path** (herding, anchoring, stale data).
- **Audit the wiring, centralize the knobs, and measure the outcomes.**
