"""
Optional LLM-as-judge faithfulness check (enabled with `python -m evals.run --judge`).

For every claim the judge sees ONLY the claim and the raw outputs of the evidence it cites, and labels it
`supported`, `partial` or `unsupported`. The LLM is injected as a callable so tests (and offline runs)
use a fake; the default factory uses the app's own structured-output LLM (needs API credit).
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from evals.metrics import iter_claims

JUDGE_PROMPT = """You are a strict fact-checker for an equity research assistant.
Decide whether the CLAIM is supported by the EVIDENCE (raw tool outputs it cites). Use no outside knowledge.
- supported: every fact and number in the claim is stated in, or directly computable from, the evidence
  (rounding such as 26.53 for 26.52708 is fine).
- partial: the core is supported but a detail (a number, direction or qualifier) is not.
- unsupported: the claim's main point is absent from or contradicted by the evidence.
Interpretive language ("suggests", "indicates") is fine when the numbers behind it are right."""


class JudgeVerdict(BaseModel):
    """Structured output of the faithfulness judge."""
    label: Literal["supported", "partial", "unsupported"]
    reason: str = Field(description="One sentence naming the fact that is or is not supported.")


JudgeFn = Callable[[str, str], dict]  # (system_prompt, user_prompt) -> {"label": ..., "reason": ...}


def default_judge_llm() -> JudgeFn:
    """Judge backed by the app's LLM (backend.agent.utils.get_structured_llm). Makes paid API calls."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.agent.utils import get_structured_llm

    llm = get_structured_llm(JudgeVerdict, temperature=0)

    def call(system: str, user: str) -> dict:
        out = llm.invoke([SystemMessage(system), HumanMessage(user)])
        return out.model_dump() if hasattr(out, "model_dump") else dict(out)

    return call


def judge_answer(answer: dict, evidence: Sequence[dict], llm: JudgeFn, max_chars: int = 2500) -> Dict:
    """Judge every claim of one answer. Returns per-claim labels plus `faithfulness` =
    (supported + 0.5 * partial) / claims (None when the answer has no claims)."""
    by_id = {e.get("id"): e for e in evidence or []}
    rows: List[dict] = []
    for c in iter_claims(answer):
        cited = [by_id[x] for x in c.get("citations") or [] if x in by_id]
        if not cited:
            rows.append({"claim": c.get("text"), "label": "unsupported", "reason": "No valid citation to check against."})
            continue
        ev_txt = "\n\n".join(f"[{e['id']}] {e.get('tool')}: {json.dumps(e.get('output'), default=str)[:max_chars]}" for e in cited)
        try:
            v = llm(JUDGE_PROMPT, f"EVIDENCE:\n{ev_txt}\n\nCLAIM: {c.get('text')}")
            label = v.get("label") if v.get("label") in ("supported", "partial", "unsupported") else "unsupported"
            rows.append({"claim": c.get("text"), "label": label, "reason": v.get("reason", "")})
        except Exception as e:  # a judge failure must not crash the run
            rows.append({"claim": c.get("text"), "label": "error", "reason": f"judge error: {e}"})
    scored = [r for r in rows if r["label"] != "error"]
    pts = sum(1.0 if r["label"] == "supported" else 0.5 if r["label"] == "partial" else 0.0 for r in scored)
    faith: Optional[float] = round(pts / len(scored), 4) if scored else None
    return {"faithfulness": faith, "claims": rows,
            "counts": {k: sum(1 for r in rows if r["label"] == k) for k in ("supported", "partial", "unsupported", "error")}}
