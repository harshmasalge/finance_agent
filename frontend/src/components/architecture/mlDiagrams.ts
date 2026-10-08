import type { DEdge, Mode, Spec } from './types';

type P = [number, number];
const e = (from: string, to: string, pts: P[], extra: Partial<DEdge> = {}): DEdge => ({ from, to, pts, ...extra });

/* ---------------------------- XGBoost ---------------------------- */

const xw = 218, xr1 = 30, xr2 = 150, xh = 72;
const xs = [16, 266, 516, 766];

export const xgboost: Spec = {
  width: 1000, height: 240, minWidth: 820,
  nodes: [
    { id: 'hist', x: xs[0], y: xr1, w: xw, h: xh, title: 'Price history', sub: '2 years of daily candles\nfor this one stock', kind: 'external',
      summary: 'The model is trained on the stock\'s own history only, fetched from Yahoo Finance when the question is asked. At least 150 trading days are needed.' },
    { id: 'feat', x: xs[1], y: xr1, w: xw, h: xh, title: 'Features', sub: 'RSI(14) · % vs 20-day EMA\n5-day return · volume ratio', kind: 'process',
      summary: 'Four features per trading day, all computed from prices and volume known on that day.',
      points: ['RSI(14): overbought / oversold', 'How far the close is above or below its 20-day EMA, in %', 'Return over the last 5 days, in %', 'Volume divided by its 20-day average'] },
    { id: 'label', x: xs[2], y: xr1, w: xw, h: xh, title: 'Label', sub: 'next 5 days: > +2% BUY\n< −2% SELL · otherwise HOLD', kind: 'process',
      summary: 'What the model learns to predict: where the price is 5 trading days later. Three classes.' },
    { id: 'split', x: xs[3], y: xr1, w: xw, h: xh, title: 'Time split', sub: 'first 80% train\nlast 20% test, never shuffled', kind: 'process',
      summary: 'The split follows time, so the model is tested on a period it has never seen, the way it will be used. Shuffling would leak the future into training.' },
    { id: 'train', x: xs[0], y: xr2, w: xw, h: xh, title: 'XGBoost classifier', sub: '3 classes · depth 3 · 80 trees', kind: 'ml',
      summary: 'Gradient-boosted decision trees with a softmax output, kept deliberately small (depth 3, 80 trees) because there are only a few hundred rows.' },
    { id: 'acc', x: xs[1], y: xr2, w: xw, h: xh, title: 'Holdout accuracy', sub: 'measured on the unseen\nlast 20%', kind: 'ml',
      summary: 'Share of test days where the predicted class was right. With three classes, a coin-toss model scores about 33%.' },
    { id: 'refit', x: xs[2], y: xr2, w: xw, h: xh, title: 'Refit & predict', sub: 'all rows → today\'s\nBUY / HOLD / SELL odds', kind: 'ml',
      summary: 'The model is refitted on all rows and asked about today. The output is a probability for each class, plus the holdout accuracy, which the Research Agent must mention.' },
    { id: 'cred', x: xs[3], y: xr2, w: xw, h: xh, title: 'Credibility weight', sub: 'clamp((accuracy − 0.33) ÷ 0.33)\n→ scorecard factor', kind: 'ml',
      summary: 'A model no better than chance gets zero say in the verdict; one right two-thirds of the time or more gets full say. The factor is (P(BUY) − P(SELL)) × 2 × credibility.' },
  ],
  edges: [
    e('hist', 'feat', [[234, 66], [266, 66]]),
    e('feat', 'label', [[484, 66], [516, 66]]),
    e('label', 'split', [[734, 66], [766, 66]]),
    e('split', 'train', [[875, 102], [875, 126], [125, 126], [125, 150]]),
    e('train', 'acc', [[234, 186], [266, 186]]),
    e('acc', 'refit', [[484, 186], [516, 186]]),
    e('refit', 'cred', [[734, 186], [766, 186]]),
  ],
};

/* ---------------------------- Prophet ---------------------------- */

const pw = 148, px = [16, 180, 344, 508, 672, 836];
export const prophet: Spec = {
  width: 1000, height: 132, minWidth: 820,
  nodes: [
    { id: 'closes', x: px[0], y: 30, w: pw, h: 72, title: 'Daily closes', sub: '2 years (Yahoo)', kind: 'external',
      summary: 'At least 100 trading days are needed.' },
    { id: 'fit', x: px[1], y: 30, w: pw, h: 72, title: 'Fit Prophet', sub: 'trend + yearly\nseasonality', kind: 'ml',
      summary: 'Meta\'s Prophet splits a series into a smooth trend plus seasonality. Daily and weekly seasonality are off; yearly seasonality is used only with 500+ days of data. The last day is held out of the fit.' },
    { id: 'fc', x: px[2], y: 30, w: pw, h: 72, title: 'Forecast', sub: 'one day ahead', kind: 'ml',
      summary: 'Forecast one step ahead and read the fitted trend for the last two days.' },
    { id: 'slope', x: px[3], y: 30, w: pw, h: 72, title: 'Trend slope', sub: '% change per day', kind: 'ml',
      summary: 'How fast the fitted trend line is rising or falling, as a percentage per day. Also reported: how far the last close sits above or below the trend.' },
    { id: 'cls', x: px[4], y: 30, w: pw, h: 72, title: 'Classify', sub: '± 0.03% per day', kind: 'process',
      summary: 'Above +0.03% a day is an uptrend, below −0.03% a downtrend, anything in between sideways. +0.03% a day is roughly +7.5% a year.' },
    { id: 'pfac', x: px[5], y: 30, w: pw, h: 72, title: 'Scorecard factor', sub: '+1 · 0 · −1', kind: 'output',
      summary: 'Uptrend +1, sideways 0, downtrend −1, with weight 1.0 in the scorecard.' },
  ],
  edges: px.slice(0, 5).map((x, i) => e(['closes', 'fit', 'fc', 'slope', 'cls'][i], ['fit', 'fc', 'slope', 'cls', 'pfac'][i], [[x + pw, 66], [px[i + 1], 66]])),
};

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
