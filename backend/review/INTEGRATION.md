# Review feature - integration steps (for the lead)

Everything below touches protected files, so it is written as snippets. Nothing else is needed:
no new Python packages (`httpx` is already in requirements), no new npm dependencies.

## 1. Backend: tables + router (`backend/main.py`)

```python
# with the other router imports
from backend.review.router import router as review_router
import backend.review.models  # noqa: F401  registers answer_status, answer_revisions, feedback, research_notes

# after app.include_router(chats_router)
app.include_router(review_router)
```

`Base.metadata.create_all` in `lifespan` then creates the four tables. Routes added:
`GET /review/{message_id}`, `POST /review/{message_id}/correct {text, target?}`,
`POST /review/{message_id}/approve {version?}`, `POST /review/{message_id}/reject {reason?}`,
`GET /review/feedback/export.jsonl`, `GET|POST /research-notes`, `GET /research-notes/{id}`.

Optional env: `NOTES_API_URL` = URL of an external research-notes platform (POST, JSON body,
`Idempotency-Key` header). Unset / `internal` = FinSight's own `/research-notes` endpoint.

## 2. Frontend: mount ReviewBar under each answer (`frontend/src/components/AIChat.tsx`)

AnswerView does not know the message id, so ReviewBar mounts next to it in AIChat:

```tsx
import ReviewBar from './review/ReviewBar';
...
{m.payload ? (
  <AnswerView payload={m.payload} ... />
) : <p className="text-[15px] text-fg-2">{m.content}</p>}
{m.payload && (
  <ReviewBar messageId={m.id} payload={m.payload}
    onPayloadChange={p => setMessages(ms => ms.map(x => (x.id === m.id ? { ...x, payload: p } : x)))} />
)}
```

ReviewBar renders nothing for `general` answers or temporary (string) message ids. Corrections also
rewrite `chat_messages.payload` to the current version, so a reloaded chat shows the corrected answer.
Optional: add `review?: { status: 'draft' | 'approved' | 'rejected'; version: number; approved_version: number | null; shown_version?: number }`
to `AnswerPayload` in `lib/api.ts` (ReviewBar currently reads it via its own `ReviewedPayload` type).

## 3. Frontend: nav entry (`frontend/src/App.tsx`)

```tsx
import { ..., FileCheck2 } from 'lucide-react';
import ResearchNotes from './components/ResearchNotes';
type Tab = 'dashboard' | 'portfolio' | 'advisor' | 'notes' | 'alerts';
// nav array, after AI Advisor
{ id: 'notes', label: 'Research Notes', icon: <FileCheck2 className="h-[18px] w-[18px]" /> },
// in <main>
{tab === 'notes' && <ResearchNotes />}
```

Both snippets were applied in a scratch copy and `tsc -b` + `vite build` passed.

## 4. Learning loop: analyst notes in synthesis (`backend/agent/synthesis.py`)

Accepted corrections become evidence items `A1, A2, ...` (tool `analyst_note`, output has `ticker`).
In `synthesis_node`, right after the scorecard block (before `reports = ...`):

```python
from backend.review.notes import analyst_notes_for

    if attempts == 1 and intent in ("research", "comparison"):  # once; evidence uses operator.add
        notes = analyst_notes_for(state.get("target_tickers") or [])
        if notes:
            update["evidence"] = (update.get("evidence") or []) + notes
            state = {**state, "evidence": (state.get("evidence") or []) + notes}
```

and add to `SYNTHESIS_RULES`:

```
7. Evidence with ids A1, A2, ... are notes from human analysts who corrected earlier answers about the same stock.
   Follow them unless fresh tool evidence contradicts them, and cite the A id when you rely on one.
```

The validator needs no change (A ids are in the evidence list). In `frontend/src/components/advisor/evidence.ts` add
`analyst_note: 'Analyst note'` to `TOOL_LABELS` and `analyst_note: 'FinSight analyst review'` to `SOURCE_LABELS`.

## 5. Optional: weights override in `backend/agent/scoring.py`

`backend/review/reweight.py` already recomputes stored cards (same formula), so this is only needed if
analyst weights should apply to *new* answers too:

```python
def _factor(name, label, value, reason, evidence_id, weights=None):
    w = (weights or WEIGHTS).get(name, WEIGHTS[name])
    return {"name": name, "label": label, "score": round(_clamp(value), 2), "weight": w, "reason": reason, "evidence_id": evidence_id}

def score_ticker(ticker, outputs, evidence_ids, weights: Optional[Dict[str, float]] = None) -> dict:
    # pass weights=weights to every _factor(...) call; coverage keeps using sum(WEIGHTS.values())
```

## 6. Tests

```
POSTGRES_URL=sqlite:// python -m pytest backend/review/tests -q
```

## 7. Offline demo (no LLM credits)

```
python -m backend.review.seed_demo --only policy   # adds "how is policy bazaar looking" as a chat
```
Open AI Advisor → that chat → Review → "Ignore the valuation factor" (HOLD → SELL, score −11.6 → −27.6),
"RSI should be 45" (pushback citing R1 = 18.2) → Approve → Research Notes → Export Markdown.
