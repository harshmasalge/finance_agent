import type { AnswerPayload, Evidence } from '../../lib/api';

/** Number each evidence item by first citation order (uncited items follow). */
export function citationNumbers(payload: AnswerPayload): Map<string, number> {
  const map = new Map<string, number>();
  for (const s of payload.answer.sections ?? []) {
    for (const c of s.claims) {
      for (const id of c.citations) {
        if (!map.has(id) && payload.evidence.some(e => e.id === id)) map.set(id, map.size + 1);
      }
    }
  }
  for (const e of payload.evidence) if (!map.has(e.id)) map.set(e.id, map.size + 1);
  return map;
}

export const TOOL_LABELS: Record<string, string> = {
  get_technical_indicators: 'Technical indicators',
  get_fundamentals: 'Fundamentals',
  get_xgboost_signal: 'XGBoost price model',
  extract_prophet_features: 'Prophet trend model',
  screen_nifty_stocks: 'NIFTY screener',
  get_recent_headlines: 'News headlines',
  get_sentiment_score: 'Sentiment score',
  get_portfolio_summary: 'Portfolio summary',
  get_position: 'Position lookup',
  compute_signal_scorecard: 'Signal scorecard',
};

export const toolLabel = (e: Evidence) => TOOL_LABELS[e.tool] ?? e.tool.replace(/_/g, ' ');

export const SOURCE_LABELS: Record<string, string> = {
  get_technical_indicators: 'Yahoo Finance · daily prices',
  get_fundamentals: 'Yahoo Finance · company data',
  get_xgboost_signal: 'Model trained on 2y prices',
  extract_prophet_features: 'Model fitted on 2y prices',
  screen_nifty_stocks: 'Yahoo Finance · 30 NIFTY stocks',
  get_recent_headlines: 'NewsAPI',
  get_sentiment_score: 'FinSight sentiment pipeline',
  get_portfolio_summary: 'Your paper portfolio',
  get_position: 'Your paper portfolio',
  compute_signal_scorecard: 'Rule-based scoring of the tool outputs above',
};
