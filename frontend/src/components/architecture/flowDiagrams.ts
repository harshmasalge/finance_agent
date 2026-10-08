import type { DEdge, Mode, Spec } from './types';

type P = [number, number];
const e = (from: string, to: string, pts: P[], extra: Partial<DEdge> = {}): DEdge => ({ from, to, pts, ...extra });

/* ================================================================== */
/* Retrieval over filings (RAG)                                        */
/* ================================================================== */

export const ragIngest: Spec = {
  width: 1000, height: 214, minWidth: 820,
  nodes: [
    { id: 'pdf', x: 16, y: 30, w: 150, h: 72, title: 'Filings (PDF)', sub: 'annual reports\ncall transcripts', kind: 'external',
      summary: 'Documents listed in a curated manifest and downloaded from the companies\' official investor-relations pages, with robots.txt respected.',
      points: ['As of the last update: 15 documents from 5 companies (HDFC Bank, TCS, ICICI Bank, SBI, Tech Mahindra)', '2,563 pages, 1,402 tables'] },
    { id: 'extract', x: 196, y: 30, w: 170, h: 72, title: 'Extract pages', sub: 'text + tables → markdown', kind: 'process',
      summary: 'PyMuPDF reads every page\'s text and font information. Tables are detected and rewritten as markdown so their numbers stay in rows and columns.',
      points: ['Scanned pages (no text layer) are flagged, not guessed', 'Each document is fingerprinted (sha256): unchanged files are skipped, changed files are redone'] },
    { id: 'chunk', x: 396, y: 30, w: 180, h: 72, title: 'Clean & chunk', sub: '≈ 420 tokens · 60 overlap\nnever crosses a page', kind: 'process',
      summary: 'Repeated headers and footers are removed, then text is split along headings into overlapping chunks. Each chunk keeps its exact page and section, so citations point to a real page.',
      points: ['420 tokens because bge-small reads at most 512: bigger chunks would be partly invisible to the vector search', 'Tiny trailing pieces are merged into the previous chunk'] },
    { id: 'embed', x: 606, y: 30, w: 160, h: 72, title: 'Embed', sub: 'bge-small-en-v1.5\non CPU', kind: 'ml',
      summary: 'A small, local sentence-embedding model turns each chunk into a 384-number vector. No external API is used. Only chunks whose text changed are re-embedded.' },
    { id: 'vstore', x: 796, y: 30, w: 188, h: 72, title: 'Chroma', sub: 'vector index (cosine)', kind: 'data',
      summary: 'Stores one vector per chunk (7,087 as of the last update) with its company, document type, page and section.' },
    { id: 'bm25', x: 606, y: 132, w: 160, h: 64, title: 'BM25 index', sub: 'keywords · in memory', kind: 'data',
      summary: 'A classic keyword index, built from the same chunks the first time a company is searched and cached until the next ingest. Strong on exact numbers and names.' },
  ],
  edges: [
    e('pdf', 'extract', [[166, 66], [196, 66]]),
    e('extract', 'chunk', [[366, 66], [396, 66]]),
    e('chunk', 'embed', [[576, 66], [606, 66]]),
    e('embed', 'vstore', [[766, 66], [796, 66]]),
    e('chunk', 'bm25', [[486, 102], [486, 164], [606, 164]]),
  ],
};

export const ragQuery: Spec = {
  width: 1000, height: 270, minWidth: 820,
  nodes: [
    { id: 'ragent', x: 16, y: 99, w: 150, h: 72, title: 'Research Agent', sub: 'stock + question', kind: 'agent',
      summary: 'Calls the filings-search tool 1–2 times per stock with targeted questions, e.g. "management guidance and outlook" or, for banks, "asset quality GNPA NNPA".' },
    { id: 'filter', x: 196, y: 99, w: 150, h: 72, title: 'Filter', sub: 'company · doc type', kind: 'process',
      summary: 'Only chunks from the requested company (and document type, if given) are searched.' },
    { id: 'kw', x: 396, y: 24, w: 180, h: 72, title: 'Keyword ranking', sub: 'BM25 · exact terms', kind: 'ml',
      summary: 'Scores chunks by the question\'s words, weighting rare words more. Good for "GNPA", "TCV" or a specific figure.' },
    { id: 'vec', x: 396, y: 174, w: 180, h: 72, title: 'Vector search', sub: 'meaning · bge + Chroma', kind: 'ml',
      summary: 'Embeds the question (with the instruction prefix bge models expect) and finds the closest chunk vectors. Good for paraphrases. If the vector store is unavailable, search falls back to keywords only.' },
    { id: 'rrf', x: 626, y: 99, w: 150, h: 72, title: 'Rank fusion', sub: 'RRF, k = 60', kind: 'ml',
      summary: 'Reciprocal rank fusion: each chunk scores 1 ÷ (60 + rank) in each list, and the two are added. It uses only ranks, so the two very different score scales never need to be compared.' },
    { id: 'top', x: 826, y: 99, w: 158, h: 72, title: 'Top 5 passages', sub: 'cited as F ids', kind: 'output',
      summary: 'Returned with document, page and section. The answer quotes figures exactly as written and cites the F id; the Sources panel and Knowledge Base page show the passage.' },
  ],
  edges: [
    e('ragent', 'filter', [[166, 135], [196, 135]]),
    e('filter', 'kw', [[346, 125], [371, 125], [371, 60], [396, 60]]),
    e('filter', 'vec', [[346, 145], [371, 145], [371, 210], [396, 210]]),
    e('kw', 'rrf', [[576, 60], [601, 60], [601, 125], [626, 125]]),
    e('vec', 'rrf', [[576, 210], [601, 210], [601, 145], [626, 145]]),
    e('rrf', 'top', [[776, 135], [826, 135]]),
  ],
};

export const ragModes: Mode[] = [
  { id: 'hybrid', label: 'Hybrid (used)', nodes: ['ragent', 'filter', 'kw', 'vec', 'rrf', 'top'],
    edges: ['ragent>filter', 'filter>kw', 'filter>vec', 'kw>rrf', 'vec>rrf', 'rrf>top'],
    summary: 'Both rankings are fused. Best at putting the right page first (highest rank-1 recall and MRR), at about 100 ms per search.' },
  { id: 'bm25', label: 'Keywords only', nodes: ['ragent', 'filter', 'kw', 'rrf', 'top'],
    edges: ['ragent>filter', 'filter>kw', 'kw>rrf', 'rrf>top'],
    summary: 'Fastest (about 8 ms) and finds the right page somewhere in the top 5 most often, because these questions are full of exact numbers and names.' },
  { id: 'vector', label: 'Vectors only', nodes: ['ragent', 'filter', 'vec', 'rrf', 'top'],
    edges: ['ragent>filter', 'filter>vec', 'vec>rrf', 'rrf>top'],
    summary: 'Weakest alone on this corpus: a small embedding model struggles with number-heavy financial text and conversational call transcripts.' },
];

/** 34-question benchmark with page-level ground truth, top 5, filtered by company (as of the last update). */
export const ragBench = [
  { id: 'hybrid', name: 'Hybrid (RRF)', r1: 0.38, r5: 0.74, mrr: 0.53, ms: '~100 ms' },
  { id: 'bm25', name: 'Keywords (BM25)', r1: 0.35, r5: 0.82, mrr: 0.52, ms: '~8 ms' },
  { id: 'vector', name: 'Vectors', r1: 0.24, r5: 0.62, mrr: 0.38, ms: '~80 ms' },
];

/* ================================================================== */
/* Expert review and the learning loop                                 */
/* ================================================================== */

export const review: Spec = {
  width: 1000, height: 484, minWidth: 820,
  nodes: [
    { id: 'draft', x: 16, y: 160, w: 120, h: 72, title: 'Answer v1', sub: 'status: Draft', kind: 'output',
      summary: 'Every advisor answer starts as a Draft. Nothing is published until an analyst approves it.' },
    { id: 'analyst', x: 166, y: 160, w: 130, h: 72, title: 'Analyst', sub: 'writes a correction', kind: 'person',
      summary: 'Types a correction in plain English in the review strip under the answer.' },
    { id: 'triage', x: 326, y: 160, w: 140, h: 72, title: 'Correction Agent', sub: 'cheapest path first', kind: 'agent',
      summary: 'Decides how to handle the correction, trying the cheapest and most predictable method first and the LLM last.' },
    { id: 'rules', x: 506, y: 40, w: 170, h: 64, title: 'Re-weight', sub: '"ignore the XGBoost signal"', kind: 'ml',
      summary: 'Weighting instructions are parsed by rules. The stored scorecard is recomputed from its factors with the new weights: same formula, same thresholds, no LLM. Claims quoting the old score are updated and an "Analyst adjustments" section is added.',
      points: ['Example: ignoring valuation turned one HOLD (−11.6) into SELL (−27.6), identically on every run'] },
    { id: 'check', x: 506, y: 164, w: 170, h: 64, title: 'Check a number', sub: '"RSI should be 45"', kind: 'process',
      summary: 'A claimed number is compared with the tool output it refers to. If it doesn\'t match, the correction is refused, citing the evidence id, tool, date and value. If it matches, claims that misstate it are fixed.' },
    { id: 'llmfix', x: 506, y: 288, w: 170, h: 64, title: 'LLM rewrite', sub: 'anything else', kind: 'agent',
      summary: 'Other corrections go to a structured LLM call, whose output is then sanitised.',
      points: ['Answer type kept; citations to non-existent evidence dropped', 'Verdict re-derived from the scorecard: the LLM cannot change it', 'The change log is computed from a real diff', 'If no LLM is available, the request fails clearly and nothing is logged'] },
    { id: 'decide', x: 716, y: 164, w: 110, h: 64, title: 'Accepted?', kind: 'process',
      summary: 'Each path either accepts the correction (a new version) or pushes back with evidence.' },
    { id: 'version', x: 866, y: 90, w: 118, h: 72, title: 'New version', sub: 'v n+1 · Draft', kind: 'output',
      summary: 'Version n+1 with a change log, authored by the analyst. Status goes back to Draft and the chat shows the new version.' },
    { id: 'push', x: 866, y: 230, w: 118, h: 72, title: 'Push back', sub: 'with evidence', kind: 'output',
      summary: 'The answer is not changed. The reply explains why, citing the evidence id that contradicts the correction.' },
    { id: 'approve', x: 166, y: 400, w: 130, h: 64, title: 'Approve', sub: 'analyst sign-off', kind: 'person',
      summary: 'Approving a Draft publishes it. Rejected answers can never be published.' },
    { id: 'publish', x: 346, y: 400, w: 170, h: 64, title: 'Research note', sub: 'published via connector', kind: 'output',
      summary: 'A research note is built from the approved version and sent through a connector, once per version (idempotent): approving twice never publishes twice. Listed on the Research Notes page.' },
    { id: 'learn', x: 566, y: 400, w: 190, h: 64, title: 'Future answers', sub: 'notes become A evidence', kind: 'agent',
      summary: 'When the same stock is researched again, approved analyst notes are added to the evidence (A ids), so the advisor follows them unless fresh data contradicts them.' },
    { id: 'log', x: 786, y: 400, w: 198, h: 64, title: 'Feedback log', sub: 'training data (JSONL)', kind: 'data',
      summary: 'Every correction, accepted or refused, is stored with its outcome and can be exported as labelled training data.' },
  ],
  edges: [
    e('draft', 'analyst', [[136, 196], [166, 196]]),
    e('analyst', 'triage', [[296, 196], [326, 196]]),
    e('triage', 'rules', [[396, 160], [396, 72], [506, 72]]),
    e('triage', 'check', [[466, 196], [506, 196]]),
    e('triage', 'llmfix', [[396, 232], [396, 320], [506, 320]]),
    e('rules', 'decide', [[676, 72], [771, 72], [771, 164]]),
    e('check', 'decide', [[676, 196], [716, 196]]),
    e('llmfix', 'decide', [[676, 320], [741, 320], [741, 228]]),
    e('decide', 'version', [[826, 186], [846, 186], [846, 126], [866, 126]], { label: 'yes', lp: [838, 150], anchor: 'end' }),
    e('decide', 'push', [[826, 206], [846, 206], [846, 266], [866, 266]], { label: 'no', lp: [838, 246], anchor: 'end' }),
    e('version', 'draft', [[925, 90], [925, 18], [76, 18], [76, 160]], { label: 'review again, or approve', lp: [500, 12], dashed: true }),
    e('decide', 'log', [[801, 228], [801, 400]], { label: 'every exchange', lp: [809, 372], anchor: 'start' }),
    e('draft', 'approve', [[76, 232], [76, 432], [166, 432]]),
    e('approve', 'publish', [[296, 432], [346, 432]]),
    e('publish', 'learn', [[516, 432], [566, 432]]),
  ],
};

export const reviewModes: Mode[] = [
  {
    id: 'weight', label: 'Change a weight',
    steps: [
      { title: 'Correction', text: '"Ignore the XGBoost signal for this one."', nodes: ['draft', 'analyst', 'triage'], edges: ['draft>analyst', 'analyst>triage'] },
      { title: 'Rules, no LLM', text: 'Recognised as a weighting change. The scorecard is recomputed from its stored factors with XGBoost at weight 0. The verdict may flip, and does so the same way every time.', nodes: ['triage', 'rules'], edges: ['triage>rules'] },
      { title: 'New version', text: 'Accepted: version n+1 with an "Analyst adjustments" section and a change log. The exchange is logged.', nodes: ['rules', 'decide', 'version', 'log'], edges: ['rules>decide', 'decide>version', 'decide>log'] },
      { title: 'Back to Draft', text: 'The new version is a Draft again. The analyst can correct further or approve it.', nodes: ['version', 'draft'], edges: ['version>draft'] },
    ],
  },
  {
    id: 'number', label: 'Dispute a number',
    steps: [
      { title: 'Correction', text: '"RSI should be 45, not 62."', nodes: ['draft', 'analyst', 'triage'], edges: ['draft>analyst', 'analyst>triage'] },
      { title: 'Check the evidence', text: 'The RSI the technical-indicators tool returned is looked up and compared with 45.', nodes: ['triage', 'check'], edges: ['triage>check'] },
      { title: 'Push back', text: 'It doesn\'t match, so the answer stays as it is. The reply cites the evidence id, the tool, the date and the value it returned. The exchange is still logged.', nodes: ['check', 'decide', 'push', 'log'], edges: ['check>decide', 'decide>push', 'decide>log'] },
    ],
  },
  {
    id: 'other', label: 'Anything else',
    steps: [
      { title: 'Correction', text: '"Mention the pending merger as a risk."', nodes: ['draft', 'analyst', 'triage'], edges: ['draft>analyst', 'analyst>triage'] },
      { title: 'LLM rewrite', text: 'A structured LLM call proposes a revised answer, or a reasoned refusal.', nodes: ['triage', 'llmfix'], edges: ['triage>llmfix'] },
      { title: 'Sanitise', text: 'Invalid citations are dropped, the verdict is re-derived from the scorecard, and the change log comes from a real diff.', nodes: ['llmfix', 'decide'], edges: ['llmfix>decide'] },
      { title: 'New version', text: 'Version n+1 is saved as a Draft and the exchange is logged.', nodes: ['decide', 'version', 'log'], edges: ['decide>version', 'decide>log'] },
    ],
  },
  {
    id: 'approve', label: 'Approve & learn',
    steps: [
      { title: 'Approve', text: 'The analyst approves the current Draft.', nodes: ['draft', 'approve'], edges: ['draft>approve'] },
      { title: 'Publish', text: 'A research note is built and published through the connector, exactly once per version.', nodes: ['approve', 'publish'], edges: ['approve>publish'] },
      { title: 'Learning loop', text: 'Next time anyone researches that stock, the note is part of the evidence the advisor reads and cites.', nodes: ['publish', 'learn'], edges: ['publish>learn'] },
    ],
  },
];

/* ================================================================== */
/* Evaluation harness                                                  */
/* ================================================================== */

export const evals: Spec = {
  width: 840, height: 352, minWidth: 720,
  nodes: [
    { id: 'ds', x: 16, y: 104, w: 150, h: 72, title: 'Test set', sub: '25 cases · every intent', kind: 'data',
      summary: 'Hand-written cases covering every intent, follow-ups, out-of-scope questions and tricky names ("policy bazaar", "L&T", "SBI", "Zomato", "HUL"), each with what a good answer must and must not contain.' },
    { id: 'replay', x: 216, y: 30, w: 170, h: 72, title: 'Replay', sub: 'recorded answers · no LLM', kind: 'process',
      summary: 'Scores answers recorded earlier. Costs nothing and gives identical numbers on every run.' },
    { id: 'live', x: 216, y: 178, w: 170, h: 72, title: 'Live', sub: 'real advisor chats', kind: 'agent',
      summary: 'Each question is asked in a real advisor chat on a chosen model; the saved chats are then scored. This makes model-against-model comparison possible.' },
    { id: 'metrics', x: 436, y: 104, w: 190, h: 72, title: 'Answer metrics', sub: 'routing · citations\ngrounding · verdict', kind: 'ml',
      summary: 'Pure, deterministic checks.',
      points: [
        'Routing accuracy and ticker precision / recall',
        'Schema validity, required sections, forbidden content',
        'Citation coverage and validity',
        'Number grounding: every number must appear in the cited evidence (with a perturbation test to prove the matcher is strict)',
        'Verdict determinism and agreement with the scorecard',
        'Latency percentiles',
      ] },
    { id: 'page', x: 676, y: 104, w: 148, h: 72, title: 'Evaluation page', sub: 'pass / fail · per model', kind: 'output',
      summary: 'The latest result for each case and model, with a drill-down per case and a link to the chat it came from.' },
    { id: 'px', x: 16, y: 272, w: 150, h: 64, title: 'NIFTY 50 history', sub: 'point in time', kind: 'external',
      summary: 'Daily prices for the NIFTY 50 and the index itself, downloaded once and cached.' },
    { id: 'bt', x: 216, y: 272, w: 170, h: 64, title: 'Backtest', sub: '12 monthly rebalances', kind: 'process',
      summary: 'Each month the scorecard is computed using only data available at that date, then each stock\'s next 30 trading days are compared with the index.',
      points: ['Price factors only: fundamentals, sentiment, Prophet and XGBoost have no point-in-time history', 'Caveats: survivorship bias, overlapping windows, one market regime, no costs'] },
    { id: 'sig', x: 436, y: 272, w: 190, h: 64, title: 'Signal metrics', sub: 'hit rate · excess return · IC', kind: 'ml',
      summary: 'Does a BUY beat the index more often than a SELL? Hit rates, mean excess return per bucket with a resampled confidence interval, and rank IC per factor.',
      points: ['Reported honestly, as of the last update: the price-only scorecard showed no edge in the tested year; RSI mean-reversion was the only factor that helped'] },
  ],
  edges: [
    e('ds', 'replay', [[166, 130], [191, 130], [191, 66], [216, 66]]),
    e('ds', 'live', [[166, 150], [191, 150], [191, 214], [216, 214]]),
    e('replay', 'metrics', [[386, 66], [411, 66], [411, 130], [436, 130]]),
    e('live', 'metrics', [[386, 214], [411, 214], [411, 150], [436, 150]]),
    e('metrics', 'page', [[626, 140], [676, 140]]),
    e('px', 'bt', [[166, 304], [216, 304]]),
    e('bt', 'sig', [[386, 304], [436, 304]]),
    e('sig', 'page', [[626, 304], [750, 304], [750, 176]]),
  ],
};
