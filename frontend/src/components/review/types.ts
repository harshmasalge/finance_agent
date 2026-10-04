// Types for the expert-review feature (mirror backend/review/service.py responses).
import type { AnswerPayload, FinalAnswer, Scorecard } from '../../lib/api';

export type ReviewStatus = 'draft' | 'approved' | 'rejected';

export interface ChangeLogEntry { path: string; before: string | null; after: string | null; reason: string; }

export interface FeedbackItem {
  id: number; message_id: number; from_version: number | null; to_version: number | null;
  correction_text: string; category: 'fact' | 'judgement' | 'weighting' | 'format'; target: string | null;
  accepted: boolean; change_log: ChangeLogEntry[]; agent_response: string | null; created_at: string | null;
}

export interface AnswerVersion {
  version: number; author: 'agent' | 'analyst'; feedback_id: number | null; created_at: string | null;
  answer: FinalAnswer; scorecards: Scorecard[];
}

export interface NoteSummary {
  id: number; message_id: number; version: number; ticker: string | null; title: string;
  verdict: 'BUY' | 'SELL' | 'HOLD' | null; published_at: string | null;
  connector_status: 'pending' | 'published' | 'received' | 'failed';
}

export interface NoteDetail extends NoteSummary {
  body: Record<string, unknown> & { headline?: string; question?: string | null; sections?: FinalAnswer['sections'] };
  connector_response: Record<string, unknown> | null;
  markdown: string;
}

/** Payload of an answer as kept in the chat, with the review block the backend adds. */
export type ReviewedPayload = AnswerPayload & {
  review?: { status: ReviewStatus; version: number; approved_version: number | null; shown_version?: number };
};

export interface ReviewState {
  message_id: number; status: ReviewStatus; version: number; current_version: number; approved_version: number | null;
  updated_at: string | null; versions: AnswerVersion[]; feedback: FeedbackItem[]; notes: NoteSummary[];
  payload: ReviewedPayload;
}

export interface CorrectResponse {
  feedback: FeedbackItem; accepted: boolean; category: FeedbackItem['category']; pushback: string | null;
  change_log: ChangeLogEntry[]; agent_response: string; source: 'rules' | 'evidence_check' | 'llm';
  new_version: number | null; review: ReviewState;
}

export interface ApproveResponse {
  publish: { status: 'published' | 'failed'; id: string | number | null; idempotent?: boolean; error?: string };
  note: NoteSummary; review: ReviewState;
}
