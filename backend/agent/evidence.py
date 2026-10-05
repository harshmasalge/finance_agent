"""
Evidence tracking: every tool call an agent makes is recorded with a short id
(e.g. R1, S2, P1). The tool's output is returned to the LLM together with that
id, so agents can cite exactly which data supports each claim, and the UI can
show the raw tool output behind every citation.
"""
import functools
import json
from datetime import datetime, timezone
from typing import Callable, Dict, List


def _json_safe(value):
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def track_tools(funcs: List[Callable], prefix: str, agent: str, sink: List[Dict]) -> List[Callable]:
    """Wrap tool functions so each call is appended to `sink` and tagged with an evidence id."""

    def wrap(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
            except Exception as e:  # never let a tool crash the agent loop
                result = {"available": False, "message": f"Tool error: {e}"}
            evidence_id = f"{prefix}{len(sink) + 1}"
            params = dict(kwargs)
            if args:
                params["args"] = list(args)
            sink.append({
                "id": evidence_id,
                "agent": agent,
                "tool": fn.__name__,
                "input": _json_safe(params),
                "output": _json_safe(result),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"evidence_id": evidence_id, "data": result}

        return wrapper

    return [wrap(f) for f in funcs]


def evidence_digest(evidence: List[Dict], max_chars: int = 1800) -> str:
    """Compact text version of the evidence list for prompts."""
    parts = []
    for e in evidence:
        if e["tool"] == "compute_signal_scorecard" and isinstance(e["output"], dict):
            c = e["output"]
            parts.append(f"[{e['id']}] Scoring Engine · scorecard({c.get('ticker')}): score {c.get('score')} -> {c.get('verdict')}, "
                         f"confidence {c.get('confidence')}\n" + "\n".join(
                             f"  - {f['label']}: {f['score']:+.2f} x weight {f['weight']} ({f['reason']})" for f in c.get("factors", [])))
            continue
        o = e["output"] if isinstance(e["output"], dict) else {}
        if e["tool"] == "search_filings" and o.get("passages"):
            # Passages carry the facts the answer quotes - keep each one readable instead of truncating the JSON.
            lines = [f"[{e['id']}] {e['agent']} · search_filings({json.dumps(e['input'])}) ticker={o.get('ticker')}"]
            for i, ps in enumerate(o["passages"], 1):
                lines.append(f"  ({i}) {ps.get('title')} p.{ps.get('page')} [{ps.get('section') or ''}]: "
                             f"{' '.join(str(ps.get('text', '')).split())[:900]}")
            parts.append("\n".join(lines))
            continue
        if e["tool"] == "get_recent_headlines" and o.get("headlines"):
            lines = [f"[{e['id']}] {e['agent']} · get_recent_headlines({json.dumps(e['input'])}) company={o.get('company')}"]
            for h in o["headlines"]:
                lines.append(f"  - {h.get('published_at', '')[:10]} {h.get('source')}: {h.get('title')} — {(h.get('description') or '')[:200]}")
            parts.append("\n".join(lines))
            continue
        out = json.dumps(e["output"], default=str)
        if len(out) > max_chars:
            out = out[:max_chars] + "...(truncated)"
        parts.append(f"[{e['id']}] {e['agent']} · {e['tool']}({json.dumps(e['input'])})\n{out}")
    return "\n\n".join(parts) if parts else "(no tool evidence collected)"
