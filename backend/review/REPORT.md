# Expert review + approve - report

An analyst reviews an agent answer in a chat strip under the answer, corrects it in plain English,
and the Correction Agent updates the answer as a new version, explains what changed (or pushes back
with the evidence id), and logs the exchange as training data. Answers stay **Draft** until
explicitly approved; approval pushes a research note through a connector.

## What was built

| Area | Files |
|---|---|
| Tables | `models.py`: `answer_status`, `answer_revisions`, `feedback`, `research_notes` (no FKs to chats so training data and published notes survive chat deletion) |
| Correction Agent | `correction.py` (`CorrectionResult`, `CorrectionAgent`), `reweight.py` (scorecard recompute + weighting parser) |
| Workflow | `service.py` (lazy v1, correct, approve, reject, note builder + Markdown, JSONL export, platform receive) |
| Connector | `connector.py` (`ResearchNotesConnector.publish`, idempotent on (message_id, version), `Idempotency-Key` header) |
| Learning loop | `notes.py` (`analyst_notes_for(tickers)` -> evidence `A1..`) |
| API | `router.py` (`/review/*`, `/research-notes*`) |
| Demo data | `seed_demo.py` (recorded answers as chats; works with no LLM credits) |
| UI | `frontend/src/components/review/{ReviewBar,DiffView,types}.tsx`, `frontend/src/components/ResearchNotes.tsx` |

## How a correction is handled (cheapest, most deterministic first)
1. **Weighting** ("ignore the XGBoost signal", "weight valuation higher", "set RSI weight to 0.5") - parsed by rules,
   the stored scorecard is recomputed from its factors (Σ score·w / Σ w × 100, card thresholds, same confidence formula);
   the verdict, the C-evidence item, claims quoting the old score/verdict and an "Analyst adjustments" section are updated. No LLM.
2. **Checkable numbers** ("RSI should be 45") - compared with the numeric tool outputs. Mismatch -> rejected, pushback
   cites the evidence id, tool, date and value. Match -> claims that misstate it are fixed, otherwise "agreed, no change".
3. **Everything else** -> injected structured LLM (`get_structured_llm(CorrectionResult)` by default). The output is
   sanitised: answer type kept, invalid citations dropped, verdict re-derived from the scorecard, change log recomputed
   from a real diff (LLM reasons kept). If the LLM is unavailable the API returns 503 with a clear message and logs nothing.

Any accepted change creates version n+1 (author `analyst`), resets status to draft, and syncs `chat_messages.payload`.

## Run
```
POSTGRES_URL=sqlite:// python -m pytest backend/review/tests -q        # 21 passed
python -m backend.review.seed_demo --only policy                         # offline demo data
```
Frontend: `npx tsc -b` and `npx vite build` pass (also with the INTEGRATION snippets applied); ESLint clean for the new files.

## Tests (`tests/test_review.py`, `tests/test_reweight.py`)
lazy v1 creation; accepted LLM correction -> v2 + change log (+ verdict cannot be changed by the LLM, bad citation dropped,
chat payload synced); rejected correction with evidence pushback (rules and LLM); "ignore valuation" flips POLICYBZR
HOLD -> SELL (−11.6 -> −27.6) identically on two runs, "weight valuation higher" -> +0.8 HOLD; approve -> publish,
re-approve idempotent, platform endpoint idempotent; external connector called once with Idempotency-Key (httpx MockTransport);
draft and rejected answers cannot be published; JSONL export labels; analyst notes A1; LLM-down -> 503; parser table.

## Known gaps
- No live LLM run (credits exhausted): free-form fact/judgement/format corrections are tested only with a fake LLM.
- UI not checked in a real browser (no browser in the VM); it uses only kit components and theme tokens.
- `ScorecardView` does not show weights, so a zero-weighted factor is explained by the "Analyst adjustments" claim, not in the card.
- Corrections are synchronous (one request, a few seconds with an LLM); no token streaming.
- Single-user app: no reviewer identity / permissions on approve. Failed external publishes are kept as `failed`; re-approving retries.

See `INTEGRATION.md` for the exact wiring steps.
