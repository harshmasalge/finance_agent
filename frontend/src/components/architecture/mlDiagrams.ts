import type { DEdge, Mode, Spec } from './types';

type P = [number, number];
const e = (from: string, to: string, pts: P[], extra: Partial<DEdge> = {}): DEdge => ({ from, to, pts, ...extra });

/* ------------------------- FinBERT news -------------------------- */

export const news: Spec = {
  width: 1000, height: 340, minWidth: 820,
  nodes: [
    { id: 'timer', x: 16, y: 30, w: 140, h: 64, title: 'Every 15 min', sub: 'market hours', kind: 'process',
      summary: 'A scheduled background job runs for every stock in the portfolio. It can also be triggered by "Check now" on the Alerts page.' },
    { id: 'src', x: 186, y: 30, w: 150, h: 64, title: 'NewsAPI + RSS', sub: 'headlines · 7 days', kind: 'external',
      summary: 'NewsAPI is searched by company name in headlines only, over the last 7 days. RSS feeds are read too, with a 10-second timeout.' },
    { id: 'match', x: 366, y: 30, w: 170, h: 64, title: 'Company matcher', sub: 'names · aliases · exclusions', kind: 'process',
      summary: 'Ticker symbols rarely appear in news ("SBIN", "TATASTEEL"), so headlines are matched by company names and aliases instead.',
      points: [
        'Whole-word matching on names and aliases (e.g. "State Bank of India", "SBI")',
        'Look-alikes are excluded: "SBI Life", "SBI Card", "HDFC Life", "ICICI Prudential"…',
        'The headline must be in English',
      ] },
    { id: 'finbert', x: 566, y: 30, w: 150, h: 64, title: 'FinBERT', sub: 'P(positive) − P(negative)', kind: 'ml',
      summary: 'A BERT model fine-tuned on financial news (ProsusAI/finbert). For each headline + description it gives positive / neutral / negative probabilities; the score is P(positive) − P(negative), from −1 to +1.',
      points: ['Loaded once per process; the label order is read from the model\'s own config', 'If it cannot load, VADER (a rule-based scorer) is used instead and the stored model name says so'] },
    { id: 'store', x: 746, y: 30, w: 238, h: 64, title: 'Stored articles', sub: 'one row per stock + URL', kind: 'data',
      summary: 'Each article is stored once per stock with its title, source, link, time and score, so every number can be traced back to real articles.' },
    { id: 'agg', x: 746, y: 150, w: 238, h: 64, title: '7-day average', sub: 'up to 25 newest distinct articles', kind: 'ml',
      summary: 'One aggregate row per stock per run: the mean score of up to 25 distinct articles from the last 7 days, with the article count.' },
    { id: 'sagent', x: 486, y: 150, w: 180, h: 64, title: 'Sentiment Agent', sub: 'cites the articles', kind: 'agent',
      summary: 'The advisor gets the average and the list of articles behind it, so answers cite real headlines. The scorecard uses the average × 2 as a factor.' },
    { id: 'mon', x: 486, y: 256, w: 180, h: 64, title: 'Alert monitor', sub: 'drop or very negative', kind: 'process',
      summary: 'Raises a sentiment alert when the average is very negative or has fallen sharply. See the Alert monitor tab.' },
  ],
  edges: [
    e('timer', 'src', [[156, 62], [186, 62]]),
    e('src', 'match', [[336, 62], [366, 62]]),
    e('match', 'finbert', [[536, 62], [566, 62]]),
    e('finbert', 'store', [[716, 62], [746, 62]]),
    e('store', 'agg', [[865, 94], [865, 150]]),
    e('agg', 'sagent', [[746, 182], [666, 182]]),
    e('agg', 'mon', [[800, 214], [800, 288], [666, 288]]),
  ],
};

/* ------------------------- Alert monitor ------------------------- */

export const monitor: Spec = {
  width: 1000, height: 344, minWidth: 820,
  nodes: [
    { id: 'hold', x: 16, y: 20, w: 170, h: 64, title: 'Your holdings', sub: 'stop-loss · target', kind: 'data',
      summary: 'Optional stop-loss and target prices set on each holding.' },
    { id: 'sin', x: 16, y: 100, w: 170, h: 64, title: 'News sentiment', sub: '7-day average', kind: 'ml',
      summary: 'The FinBERT aggregate from the news job.' },
    { id: 'candles', x: 16, y: 220, w: 170, h: 64, title: 'Daily candles', sub: '3 months (Yahoo)', kind: 'external',
      summary: 'Three months of daily candles from Yahoo Finance, with the app\'s own price table as a fallback.' },
    { id: 'sl', x: 246, y: 20, w: 210, h: 64, title: 'Stop-loss / target', sub: 'price crosses a level', kind: 'process',
      summary: 'Fires when the price falls to the stop-loss or rises to the target.' },
    { id: 'srule', x: 246, y: 100, w: 210, h: 64, title: 'Sentiment', sub: '≤ −0.35, or fell ≥ 0.35 in a day', kind: 'process',
      summary: 'Fires when the 7-day average is −0.35 or lower, or has fallen by 0.35 or more against the average from about a day earlier.' },
    { id: 'rsi', x: 246, y: 180, w: 210, h: 64, title: 'RSI (14)', sub: '> 75 overbought · < 30 oversold', kind: 'process',
      summary: 'Wilder\'s RSI over 14 daily closes.' },
    { id: 'vol', x: 246, y: 260, w: 210, h: 64, title: 'Volume spike', sub: '> 3 × the 20-day average', kind: 'process',
      summary: 'Today\'s volume compared with the average of the previous 20 sessions.' },
    { id: 'cool', x: 516, y: 140, w: 170, h: 64, title: 'Cooldown', sub: 'no repeats per stock & type', kind: 'process',
      summary: 'The same alert type for the same stock is not raised again within its cooldown window, so one event does not produce a stream of identical alerts.' },
    { id: 'out', x: 746, y: 140, w: 238, h: 64, title: 'Alert + citations', sub: 'saved · pushed live · Alerts page', kind: 'output',
      summary: 'Every alert carries citations: the articles or the price data it was raised on. It is saved, pushed to the browser over the WebSocket, and listed on the Alerts page with numbered sources.' },
  ],
  edges: [
    e('hold', 'sl', [[186, 52], [246, 52]]),
    e('sin', 'srule', [[186, 132], [246, 132]]),
    e('candles', 'rsi', [[186, 252], [216, 252], [216, 212], [246, 212]]),
    e('candles', 'vol', [[186, 252], [216, 252], [216, 292], [246, 292]]),
    e('sl', 'cool', [[456, 52], [486, 52], [486, 166], [516, 166]]),
    e('srule', 'cool', [[456, 132], [486, 132], [486, 166], [516, 166]]),
    e('rsi', 'cool', [[456, 212], [486, 212], [486, 178], [516, 178]]),
    e('vol', 'cool', [[456, 292], [486, 292], [486, 178], [516, 178]]),
    e('cool', 'out', [[686, 172], [746, 172]], { label: 'new?', lp: [716, 162] }),
  ],
};

export const monitorModes: Mode[] = [
  {
    id: 'sl', label: 'Stop-loss / target',
    summary: 'Signal: SELL. The price reached the stop-loss or the target set on the holding. Cooldown 24 hours.',
    nodes: ['hold', 'sl', 'cool', 'out'], edges: ['hold>sl', 'sl>cool', 'cool>out'],
  },
  {
    id: 'sent', label: 'Sentiment',
    summary: 'Needs a fresh average (under 3 hours old) built from at least 3 articles. Fires at −0.35 or lower, or after a fall of 0.35 or more against the latest average from at least 20 hours earlier. The alert quotes the most negative articles. Cooldown 12 hours.',
    nodes: ['sin', 'srule', 'cool', 'out'], edges: ['sin>srule', 'srule>cool', 'cool>out'],
  },
  {
    id: 'rsi', label: 'RSI',
    summary: 'RSI above 75 is overbought (signal SELL: consider booking profits); below 30 is oversold (signal BUY: possible entry). Needs at least 15 closes. Cooldown 20 hours.',
    nodes: ['candles', 'rsi', 'cool', 'out'], edges: ['candles>rsi', 'rsi>cool', 'cool>out'],
  },
  {
    id: 'vol', label: 'Volume',
    summary: 'Today\'s volume above 3 × the average of the previous 20 sessions: something is happening, so the signal is HOLD and look closer. Cooldown 20 hours.',
    nodes: ['candles', 'vol', 'cool', 'out'], edges: ['candles>vol', 'vol>cool', 'cool>out'],
  },
];
