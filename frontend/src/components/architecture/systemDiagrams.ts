import type { DEdge, Mode, Spec } from './types';

type P = [number, number];
const e = (from: string, to: string, pts: P[], extra: Partial<DEdge> = {}): DEdge => ({ from, to, pts, ...extra });

/* ================================================================== */
/* 1. System overview                                                  */
/* ================================================================== */

export const overview: Spec = {
  width: 1000, height: 584, minWidth: 820,
  groups: [
    { x: 316, y: 124, w: 370, h: 276, label: 'API container' },
    { x: 706, y: 124, w: 278, h: 276, label: 'Worker containers' },
  ],
  nodes: [
    {
      id: 'browser', x: 16, y: 300, w: 130, h: 72, title: 'Browser', sub: 'React + Vite app', kind: 'client',
      summary: 'A single-page React app. Every screen has its own URL, so back, forward, reload and bookmarks all work.',
      points: [
        'Screens: Dashboard, Portfolio, AI Advisor, Research Notes, Knowledge Base, Evaluation, Alerts and this page',
        'Light and dark themes',
        'Each chat can run on a different LLM; the sidebar sets the default for new chats',
        'Shows advisor progress live and keeps a run going when you switch screens',
      ],
    },
    {
      id: 'caddy', x: 170, y: 300, w: 122, h: 72, title: 'Caddy', sub: 'HTTPS · /api proxy', kind: 'infra',
      summary: 'The web server in front of everything, and the only container reachable from the internet (ports 80 and 443).',
      points: [
        'Gets and renews HTTPS certificates automatically',
        'Serves the built front end',
        'Forwards /api/* to FastAPI',
        'Flushes the progress stream immediately, so agent steps appear as they happen',
      ],
    },
    {
      id: 'api', x: 336, y: 300, w: 330, h: 72, title: 'FastAPI', sub: 'REST · SSE stream · WebSocket', kind: 'service',
      summary: 'The Python backend. It serves the REST API, streams agent progress to the browser, and pushes live prices and alerts.',
      points: [
        'REST endpoints for portfolio and paper trades, chats, alerts, review, knowledge base and evaluation',
        'Server-sent events (SSE) stream every agent step while a question is being answered',
        'One WebSocket per user for live prices and new alerts',
        'Public browse-only mode switches off everything that would spend LLM credit',
      ],
    },
    {
      id: 'agent', x: 336, y: 152, w: 220, h: 72, title: 'Agent runtime', sub: 'LangGraph · background runs', kind: 'agent',
      summary: 'A LangGraph state machine. An orchestrator routes each question to specialist agents; a synthesis step writes a cited answer and a validator checks it.',
      points: [
        'Each question runs as a background task, so leaving the page does not stop it',
        'Every step is recorded, so a returning browser can replay the progress so far',
        'The model is chosen per chat',
        'Every API key of a provider is used in turn; a rate-limited or out-of-credit key is skipped and rested',
      ],
    },
    {
      id: 'chroma', x: 572, y: 152, w: 94, h: 72, title: 'Chroma', sub: 'vectors', kind: 'data',
      summary: 'Vector database holding embeddings of company filing passages. In production it runs inside the API container.',
      points: [
        'Cosine similarity over bge-small embeddings computed on the CPU',
        'Paired with an in-memory keyword (BM25) index for hybrid search',
        'Read by the filings-search tool of the Research Agent',
      ],
    },
    {
      id: 'llm', x: 336, y: 24, w: 180, h: 60, title: 'LLM providers', sub: '4 providers · key pool', kind: 'external',
      summary: 'Large language models used to route questions, run the tool-using agents, and write and check answers.',
      points: [
        'Groq, OpenRouter, Google Gemini and Anthropic Claude',
        'All keys configured for a provider are used round robin; on a 401, 402, 403 or 429 the same request moves to the next key',
        'Structured output (JSON schema or tool calling) for every decision the code relies on',
      ],
    },
    {
      id: 'yahoo', x: 532, y: 24, w: 190, h: 60, title: 'Yahoo Finance', sub: 'prices · fundamentals', kind: 'external',
      summary: 'Market data source.',
      points: [
        '2 years of daily candles for technical indicators, XGBoost and Prophet',
        'Fundamentals such as P/E and growth',
        'Live prices for the dashboard',
        '3 months of daily candles for RSI and volume alerts',
      ],
    },
    {
      id: 'news', x: 780, y: 24, w: 170, h: 60, title: 'NewsAPI + RSS', sub: 'headlines, last 7 days', kind: 'external',
      summary: 'Headline sources for news sentiment.',
      points: [
        'NewsAPI is searched by company name in headlines over the last 7 days',
        'RSS feeds are a second source',
        'Only English headlines that actually name the company are kept',
      ],
    },
    {
      id: 'worker', x: 726, y: 152, w: 238, h: 72, title: 'Celery worker', sub: 'prices · news · alerts', kind: 'service',
      summary: 'Runs the scheduled background jobs.',
      points: [
        'Live prices every minute in market hours',
        'End-of-day candles at 15:30 IST',
        'News ingestion and FinBERT scoring every 15 minutes',
        'Portfolio monitor (alerts) every 15 minutes',
        'FinBERT is loaded once per worker process',
      ],
    },
    {
      id: 'beat', x: 726, y: 300, w: 150, h: 60, title: 'Celery beat', sub: 'IST market hours', kind: 'service',
      summary: 'The scheduler. Fires jobs on a timetable in Indian time, on weekdays only, and hands them to the worker through Redis.',
      points: ['Every minute 09:00–15:59: live prices', '15:30: end-of-day candles', 'Every 15 minutes 09:00–16:45: news sentiment and the portfolio monitor'],
    },
    {
      id: 'pg', x: 336, y: 474, w: 170, h: 64, title: 'PostgreSQL', sub: 'with TimescaleDB', kind: 'data',
      summary: 'The main database.',
      points: [
        'Users, holdings and paper trades',
        'Chats and messages, including each answer with its evidence',
        'News articles, sentiment scores, and alerts with their citations',
        'Answer versions, analyst feedback and published research notes',
      ],
    },
    {
      id: 'redis', x: 556, y: 474, w: 150, h: 64, title: 'Redis', sub: 'task queue · pub/sub', kind: 'data',
      summary: 'Two jobs: the Celery task queue, and publish/subscribe channels for live updates.',
      points: ['A live-prices channel', 'A user-alerts channel', 'FastAPI listens to both and forwards messages to open WebSockets'],
    },
    {
      id: 'models', x: 744, y: 474, w: 220, h: 64, title: 'Model cache', sub: 'FinBERT · bge-small', kind: 'ml',
      summary: 'Hugging Face models downloaded once and kept on a shared volume.',
      points: [
        'FinBERT scores the tone of financial headlines',
        'bge-small-en-v1.5 embeds filing passages and search queries',
        'XGBoost and Prophet are not stored: they are fitted fresh for each stock when a question needs them',
      ],
    },
  ],
  edges: [
    e('browser', 'caddy', [[146, 336], [170, 336]]),
    e('caddy', 'api', [[292, 336], [336, 336]]),
    e('api', 'agent', [[420, 300], [420, 224]], { label: 'start run', lp: [412, 266], anchor: 'end' }),
    e('agent', 'api', [[520, 224], [520, 300]], { label: 'progress events', lp: [528, 266], anchor: 'start' }),
    e('agent', 'llm', [[426, 152], [426, 84]], { label: 'prompts · tool calls', lp: [434, 122], anchor: 'start' }),
    e('agent', 'yahoo', [[546, 152], [546, 84]], { label: 'market data', lp: [554, 122], anchor: 'start' }),
    e('agent', 'chroma', [[556, 188], [572, 188]]),
    e('worker', 'yahoo', [[750, 152], [750, 108], [700, 108], [700, 84]], { label: 'prices', lp: [758, 132], anchor: 'start' }),
    e('news', 'worker', [[865, 84], [865, 152]], { label: 'headlines', lp: [873, 122], anchor: 'start' }),
    e('beat', 'worker', [[800, 300], [800, 224]], { label: 'schedules', lp: [808, 266], anchor: 'start' }),
    e('worker', 'models', [[905, 224], [905, 474]], { label: 'FinBERT', lp: [913, 440], anchor: 'start' }),
    e('worker', 'redis', [[726, 206], [696, 206], [696, 474]], { label: 'publish', lp: [688, 446], anchor: 'end' }),
    e('redis', 'api', [[600, 474], [600, 372]], { label: 'subscribe', lp: [592, 424], anchor: 'end' }),
    e('api', 'pg', [[440, 372], [440, 474]], { label: 'SQL', lp: [448, 424], anchor: 'start' }),
    e('worker', 'pg', [[964, 188], [990, 188], [990, 566], [421, 566], [421, 538]], { label: 'articles · scores · alerts', lp: [700, 560] }),
  ],
};

export const overviewModes: Mode[] = [
  {
    id: 'ask', label: 'Ask the advisor',
    steps: [
      { title: 'You ask', text: 'The browser sends your question over HTTPS. Caddy passes /api requests to FastAPI.', nodes: ['browser', 'caddy', 'api'], edges: ['browser>caddy', 'caddy>api'] },
      { title: 'Run starts', text: 'FastAPI starts the agent graph as a background task and returns at once. The run keeps going even if you leave the page.', nodes: ['api', 'agent'], edges: ['api>agent'] },
      { title: 'Agents gather evidence', text: 'The agents call LLMs, pull market data from Yahoo Finance and search company filings in Chroma. Every tool result becomes a numbered piece of evidence.', nodes: ['agent', 'llm', 'yahoo', 'chroma'], edges: ['agent>llm', 'agent>yahoo', 'agent>chroma'] },
      { title: 'Progress streams back', text: 'Each step is sent to the browser as it happens (server-sent events). This is the live list of agent steps under your question.', nodes: ['agent', 'api', 'caddy', 'browser'], edges: ['agent>api', 'caddy>api', 'browser>caddy'] },
      { title: 'Answer saved', text: 'The finished answer, with its evidence, is saved to the chat in PostgreSQL, so it is there when you come back.', nodes: ['api', 'pg'], edges: ['api>pg'] },
    ],
  },
  {
    id: 'prices', label: 'Live prices',
    steps: [
      { title: 'Timer fires', text: 'Every minute in market hours, Celery beat queues a price job for the worker.', nodes: ['beat', 'worker'], edges: ['beat>worker'] },
      { title: 'Fetch prices', text: 'The worker fetches the latest prices from Yahoo Finance.', nodes: ['worker', 'yahoo'], edges: ['worker>yahoo'] },
      { title: 'Publish', text: 'Each update is published to a live-prices channel in Redis.', nodes: ['worker', 'redis'], edges: ['worker>redis'] },
      { title: 'Push to browser', text: 'FastAPI is subscribed to that channel and forwards each message over your WebSocket. The green "Live" dot in the sidebar shows the socket is connected.', nodes: ['redis', 'api', 'caddy', 'browser'], edges: ['redis>api', 'caddy>api', 'browser>caddy'] },
    ],
  },
  {
    id: 'alert', label: 'News to alert',
    steps: [
      { title: 'Every 15 minutes', text: 'In market hours, Celery beat queues news ingestion and then the portfolio monitor.', nodes: ['beat', 'worker'], edges: ['beat>worker'] },
      { title: 'Collect headlines', text: 'For each holding the worker pulls recent headlines from NewsAPI and RSS and keeps only the ones that really name the company.', nodes: ['news', 'worker'], edges: ['news>worker'] },
      { title: 'Score the tone', text: 'FinBERT, a model trained on financial text, scores every headline from −1 (bearish) to +1 (bullish).', nodes: ['worker', 'models'], edges: ['worker>models'] },
      { title: 'Store and check', text: 'Articles and a 7-day average per stock are saved. The monitor then checks stop-loss/target, sentiment, RSI and volume rules.', nodes: ['worker', 'pg'], edges: ['worker>pg'] },
      { title: 'Alert pushed', text: 'A new alert, with the articles or data it was based on, is published to Redis and pushed to the browser: a toast, the badge on Alerts, and the Alerts page.', nodes: ['worker', 'redis', 'api', 'caddy', 'browser'], edges: ['worker>redis', 'redis>api', 'caddy>api', 'browser>caddy'] },
    ],
  },
];

/* ================================================================== */
/* 2. Advisor pipeline                                                 */
/* ================================================================== */

export const pipeline: Spec = {
  width: 1000, height: 512, minWidth: 820,
  nodes: [
    {
      id: 'q', x: 16, y: 224, w: 104, h: 72, title: 'Question', sub: '+ chat history', kind: 'person',
      summary: 'Your latest message plus up to 8 earlier ones, so follow-ups like "what about Infosys?" are understood.',
    },
    {
      id: 'orch', x: 150, y: 224, w: 136, h: 72, title: 'Orchestrator', sub: 'intent · tickers', kind: 'agent',
      summary: 'One structured LLM call that sorts the question into one of seven intents and turns company names into NSE tickers.',
      points: [
        'Intents: research, comparison, sentiment, portfolio, ideas, clarify, direct answer',
        'A research or sentiment question with no stock named becomes "clarify"',
        'A comparison with fewer than two stocks becomes research (or clarify)',
        'Tickers get the .NS suffix; non-Indian securities are never produced',
        'Also loads which stocks you hold, for the Risk Agent and ideas',
      ],
    },
    {
      id: 'research', x: 326, y: 64, w: 170, h: 72, title: 'Research Agent', sub: 'technicals · ML · filings', kind: 'agent',
      summary: 'A ReAct agent: it decides which tools to call, reads the results and calls more until it has what it needs.',
      points: [
        'Technical indicators: EMA 20/50/200, RSI(14), MACD, 1- and 3-month returns, 52-week range',
        'Fundamentals: P/E, earnings and revenue growth',
        'XGBoost 5-day signal and Prophet trend (see Machine learning)',
        'Filings search over annual reports and earnings calls (see Retrieval)',
        'NIFTY screener for "ideas" questions',
        'Rule: numbers may only come from tool results, never from memory',
      ],
    },
    {
      id: 'sentiment', x: 326, y: 224, w: 170, h: 72, title: 'Sentiment Agent', sub: 'headlines · FinBERT', kind: 'agent',
      summary: 'Reads the news around the stocks in question.',
      points: [
        'Recent headlines, each with its own FinBERT score',
        'The 7-day sentiment average and the articles behind it',
        'If no fresh average is stored, it scores live headlines on the spot',
      ],
    },
    {
      id: 'risk', x: 326, y: 384, w: 170, h: 72, title: 'Risk Agent', sub: 'your portfolio', kind: 'agent',
      summary: 'Looks at your paper-trading portfolio.',
      points: ['Portfolio summary: positions, weights, concentration, profit and loss', 'Details of a single position', 'Flags overlap when ideas would add to a sector you already hold'],
    },
    {
      id: 'notes', x: 540, y: 64, w: 130, h: 72, title: 'Analyst notes', sub: 'approved feedback', kind: 'person',
      summary: 'Corrections an analyst has approved for the same stocks are added as evidence (A ids). A correction made once shapes later answers.',
      points: ['Research and comparison questions only', 'Added to the first draft; never allowed to break an answer'],
    },
    {
      id: 'evidence', x: 540, y: 224, w: 130, h: 72, title: 'Evidence pool', sub: 'numbered · cited', kind: 'data',
      summary: 'Every tool call is recorded with an id that claims must cite. The Sources panel next to each answer shows these items.',
      points: ['R = research, S = sentiment, P = portfolio', 'F = filing passage, C = scorecard, A = analyst note'],
    },
    {
      id: 'scoring', x: 540, y: 384, w: 130, h: 72, title: 'Scoring engine', sub: 'fixed rules', kind: 'ml',
      summary: 'Turns the research and sentiment evidence into BUY / HOLD / SELL with fixed weights. The LLM never chooses the verdict, so the same data always gives the same verdict.',
      points: ['9 factors, each scored from −1 to +1', 'Score ≥ +15 is BUY, ≤ −15 is SELL', 'Try it in the Machine learning section'],
    },
    {
      id: 'synth', x: 712, y: 224, w: 120, h: 72, title: 'Synthesis', sub: 'cited answer', kind: 'agent',
      summary: 'Writes the answer as sections of short claims, each citing evidence ids.',
      points: [
        'The format depends on the intent (stock analysis, comparison, portfolio review, ideas…)',
        'Verdict and confidence are copied from the scorecard',
        'Data gaps reported by the agents are carried over',
        'On a revision it is given the validator\'s list of problems',
      ],
    },
    {
      id: 'validator', x: 870, y: 224, w: 114, h: 72, title: 'Validator', sub: 'rules + LLM', kind: 'agent',
      summary: 'Checks the draft in two layers before you see it.',
      points: [
        'Rules: at least two sections; a section per stock in comparisons; every claim cited; cited ids exist; no non-Indian securities; stock analyses have a verdict',
        'LLM judge: unsupported numbers or facts, text that contradicts the scorecard, missing data treated as known',
        'Problems found → one revision; if it still fails, the answer is shown with a warning',
        'General replies are not checked',
      ],
    },
    {
      id: 'answer', x: 870, y: 384, w: 114, h: 72, title: 'Answer', sub: 'verdict · sources', kind: 'output',
      summary: 'Shown with the verdict, confidence, scorecard and a Sources panel. It starts as a Draft that an analyst can correct and approve.',
    },
  ],
  edges: [
    e('q', 'orch', [[120, 260], [150, 260]]),
    e('orch', 'research', [[286, 248], [306, 248], [306, 100], [326, 100]]),
    e('orch', 'sentiment', [[286, 260], [326, 260]]),
    e('orch', 'risk', [[286, 272], [306, 272], [306, 420], [326, 420]]),
    e('research', 'evidence', [[496, 100], [516, 100], [516, 248], [540, 248]]),
    e('sentiment', 'evidence', [[496, 260], [540, 260]]),
    e('risk', 'evidence', [[496, 420], [516, 420], [516, 272], [540, 272]]),
    e('notes', 'evidence', [[605, 136], [605, 224]], { label: 'A ids', lp: [613, 184], anchor: 'start' }),
    e('evidence', 'scoring', [[605, 296], [605, 384]], { label: 'R + S evidence', lp: [613, 344], anchor: 'start' }),
    e('scoring', 'synth', [[670, 420], [692, 420], [692, 272], [712, 272]], { label: 'C ids', lp: [700, 412], anchor: 'start' }),
    e('evidence', 'synth', [[670, 248], [712, 248]]),
    e('synth', 'validator', [[832, 260], [870, 260]]),
    e('validator', 'answer', [[927, 296], [927, 384]], { label: 'passed', lp: [935, 344], anchor: 'start' }),
    e('validator', 'synth', [[927, 224], [927, 192], [772, 192], [772, 224]], { label: 'problems → revise once', lp: [850, 184], dashed: true }),
    e('orch', 'synth', [[218, 296], [218, 492], [772, 492], [772, 296]], { label: 'clarify · general question', lp: [495, 486] }),
  ],
};

const FULL = ['q>orch', 'orch>research', 'orch>sentiment', 'orch>risk', 'research>evidence', 'sentiment>evidence', 'risk>evidence',
  'notes>evidence', 'evidence>scoring', 'scoring>synth', 'evidence>synth', 'synth>validator', 'validator>answer'];
const tail = ['evidence>synth', 'synth>validator', 'validator>answer'];

export const intents: Mode[] = [
  {
    id: 'research', label: 'Research',
    summary: '"Should I buy Tech Mahindra?" All three agents run in parallel. The scoring engine computes the verdict, approved analyst notes are added, and the validator checks every citation.',
    nodes: ['q', 'orch', 'research', 'sentiment', 'risk', 'notes', 'evidence', 'scoring', 'synth', 'validator', 'answer'],
    edges: FULL, past: ['validator>synth'],
  },
  {
    id: 'comparison', label: 'Comparison',
    summary: '"Compare TCS and Infosys." Same path as research, with one scorecard per stock. The answer must have a section for each stock and a head-to-head.',
    nodes: ['q', 'orch', 'research', 'sentiment', 'risk', 'notes', 'evidence', 'scoring', 'synth', 'validator', 'answer'],
    edges: FULL, past: ['validator>synth'],
  },
  {
    id: 'sentiment', label: 'Sentiment',
    summary: '"What\'s the news on SBI?" Only the Sentiment Agent runs. No scorecard, so no BUY/SELL verdict.',
    nodes: ['q', 'orch', 'sentiment', 'evidence', 'synth', 'validator', 'answer'],
    edges: ['q>orch', 'orch>sentiment', 'sentiment>evidence', ...tail], past: ['validator>synth'],
  },
  {
    id: 'portfolio', label: 'Portfolio',
    summary: '"How risky is my portfolio?" Only the Risk Agent runs, on your paper-trading holdings.',
    nodes: ['q', 'orch', 'risk', 'evidence', 'synth', 'validator', 'answer'],
    edges: ['q>orch', 'orch>risk', 'risk>evidence', ...tail], past: ['validator>synth'],
  },
  {
    id: 'ideas', label: 'Ideas',
    summary: '"What should I add to diversify?" The Research Agent screens about 30 liquid NIFTY 50 stocks on momentum and trend (excluding what you hold) and checks fundamentals of the top three. The Risk Agent adds your current exposure.',
    nodes: ['q', 'orch', 'research', 'risk', 'evidence', 'synth', 'validator', 'answer'],
    edges: ['q>orch', 'orch>research', 'orch>risk', 'research>evidence', 'risk>evidence', ...tail], past: ['validator>synth'],
  },
  {
    id: 'clarify', label: 'Clarify / general',
    summary: '"Is it a good buy?" with no stock named, or "What is a P/E ratio?" No agents run: the reply is written directly and is not checked by the validator.',
    nodes: ['q', 'orch', 'synth', 'validator', 'answer'],
    edges: ['q>orch', 'orch>synth', 'synth>validator', 'validator>answer'],
  },
];
