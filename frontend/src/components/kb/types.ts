// Types for the /kb (knowledge base) API — mirror backend/rag/router.py.

export type KbDocType = 'annual_report' | 'earnings_call';

export interface KbDoc {
  doc_id: string; ticker: string; company: string; doc_type: KbDocType; fiscal_year: string;
  period: string | null; title: string; pages: number | null; chunks: number | null; tables: number | null;
  status: 'pending' | 'downloaded' | 'extracting' | 'extracted' | 'indexed' | 'failed_download' | 'failed_ingest';
  scanned_pages: number[]; empty_pages: number[]; error: string | null; source_url: string | null;
  page_url: string | null; updated_at: string | null; has_file: boolean;
}

export interface KbStats {
  documents: number; by_status: Record<string, number>; companies: string[]; pages: number; chunks: number;
  tables: number; scanned_pages: number; vectors: number | null; vector_store: 'http' | 'embedded' | null;
  embedding_model: string; chunk_tokens: number;
  ingest: { running: boolean; last: unknown; error: string | null };
}

export interface KbHit {
  doc_id: string; ticker: string; company: string; title: string; doc_type: KbDocType; fiscal_year: string;
  page: number; section: string; text: string; has_table: boolean; score: number;
  bm25_rank: number | null; vector_rank: number | null; url: string;
}

export interface KbSearchResponse { query: string; ticker: string | null; mode: string; results: KbHit[]; }

export interface KbScores { 'recall@1': number; 'recall@5': number; mrr: number; }
export interface KbBenchmark {
  available: boolean; message?: string; generated_at?: string; n_questions?: number; k?: number;
  corpus?: { documents: number; indexed: number; pages: number; chunks: number; tables: number };
  retrieval?: { modes: Record<string, { strict: KbScores; lenient: KbScores; latency_ms_p50: number; latency_ms_p95: number }> };
  tables?: { checked: number; passed: number };
  ingest_speed?: { extract_pages_per_sec: number | null; embed_chunks_per_sec?: number; embedding_model?: string };
}

/** Shape of the `search_filings` tool output stored in evidence items with id prefix `F`. */
export interface FilingPassage {
  doc_id: string; title: string; doc_type: KbDocType; fiscal_year: string; page: number;
  section: string; text: string; score: number; url: string;
}
export interface SearchFilingsOutput {
  available: boolean; ticker: string; query: string; passages: FilingPassage[]; message?: string;
}
