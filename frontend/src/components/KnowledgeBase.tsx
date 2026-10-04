import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { AlertTriangle, BookOpen, Database, ExternalLink, FileText, Gauge, RefreshCw, Search, Table2 } from 'lucide-react';
import { api, API_URL } from '../lib/api';
import { cn, tickerLabel } from '../lib/format';
import { useToast } from './toast';
import { Badge, Button, Card, CardHeader, EmptyState, Input, PageHeader, Segmented, Select, Skeleton, Stat } from './ui';
import type { KbBenchmark, KbDoc, KbHit, KbSearchResponse, KbStats } from './kb/types';

const TYPE_LABEL: Record<string, string> = { annual_report: 'Annual report', earnings_call: 'Earnings call' };
const STATUS_TONE: Record<string, 'up' | 'warn' | 'down' | 'neutral' | 'primary'> = {
  indexed: 'up', extracted: 'primary', extracting: 'warn', downloaded: 'neutral', pending: 'neutral',
  failed_download: 'down', failed_ingest: 'down',
};
type Mode = 'hybrid' | 'bm25' | 'vector';

const pct = (v?: number) => (v === undefined ? '—' : `${Math.round(v * 100)}%`);
const fileUrl = (path: string) => `${API_URL}${path}`;

/** Render a passage: markdown tables become real tables, other lines stay text. */
function PassageText({ text }: { text: string }) {
  const blocks: { table: boolean; lines: string[] }[] = [];
  for (const line of text.split('\n')) {
    const isRow = line.trim().startsWith('|') && line.trim().endsWith('|');
    const last = blocks[blocks.length - 1];
    if (last && last.table === isRow) last.lines.push(line);
    else blocks.push({ table: isRow, lines: [line] });
  }
  return (
    <div className="space-y-2 text-[13px] leading-relaxed text-fg-2">
      {blocks.map((b, i) => {
        if (!b.table) return <p key={i} className="whitespace-pre-line">{b.lines.join('\n')}</p>;
        const rows = b.lines.filter(l => !/^\|\s*:?-{2,}/.test(l.trim())).map(l => l.trim().slice(1, -1).split('|').map(c => c.replace(/\*\*/g, '').trim()));
        return (
          <div key={i} className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-[12px]">
              <tbody>{rows.map((r, j) => (
                <tr key={j} className={cn(j > 0 && 'border-t border-border', j === 0 && 'bg-surface-2 font-medium text-fg')}>
                  {r.map((c, k) => <td key={k} className="px-2.5 py-1.5 align-top tabular">{c}</td>)}
                </tr>
              ))}</tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

function HitCard({ hit }: { hit: KbHit }) {
  const [open, setOpen] = useState(false);
  const long = hit.text.length > 700;
  return (
    <li className="rounded-xl border border-border bg-surface p-4 transition-colors hover:border-border-strong">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="primary">{tickerLabel(hit.ticker)}</Badge>
        <span className="text-[13px] font-medium text-fg">{hit.title}</span>
        <span className="text-[12px] text-muted">· p. {hit.page}</span>
        {hit.has_table && <Badge><Table2 className="h-3 w-3" />Table</Badge>}
        <a href={fileUrl(hit.url)} target="_blank" rel="noreferrer"
          className="ml-auto inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">
          Open PDF <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      {hit.section && <div className="mt-1 truncate text-[12px] text-muted" title={hit.section}>{hit.section}</div>}
      <div className={cn('mt-2', !open && long && 'max-h-48 overflow-hidden [mask-image:linear-gradient(to_bottom,black_70%,transparent)]')}>
        <PassageText text={hit.text} />
      </div>
      <div className="mt-2 flex items-center gap-3 text-[11px] text-muted tabular">
        <span>score {hit.score.toFixed(4)}</span>
        <span>BM25 #{hit.bm25_rank ?? '—'}</span>
        <span>vector #{hit.vector_rank ?? '—'}</span>
        {long && <button type="button" onClick={() => setOpen(o => !o)} className="ml-auto font-medium text-primary hover:underline">{open ? 'Show less' : 'Show more'}</button>}
      </div>
    </li>
  );
}

function BenchmarkCard({ bench }: { bench: KbBenchmark | null }) {
  if (!bench) return <Card className="p-5"><Skeleton className="h-24 w-full" /></Card>;
  if (!bench.available) {
    return (
      <Card>
        <CardHeader title="Retrieval benchmark" />
        <EmptyState icon={<Gauge className="h-5 w-5" />} title="No benchmark yet" body={bench.message} />
      </Card>
    );
  }
  const modes = bench.retrieval?.modes ?? {};
  return (
    <Card>
      <CardHeader title="Retrieval benchmark"
        subtitle={`${bench.n_questions} analyst questions with page-level ground truth · top-${bench.k}`} />
      <div className="overflow-x-auto px-5">
        <table className="w-full text-[13px]">
          <thead><tr className="text-left text-[12px] text-muted">
            <th className="py-1.5 font-medium">Retriever</th><th className="py-1.5 text-right font-medium">Recall@1</th>
            <th className="py-1.5 text-right font-medium">Recall@5</th><th className="py-1.5 text-right font-medium">MRR</th>
            <th className="py-1.5 text-right font-medium">p50</th>
          </tr></thead>
          <tbody>{Object.entries(modes).map(([m, v]) => (
            <tr key={m} className={cn('border-t border-border', m === 'hybrid' && 'font-semibold text-fg')}>
              <td className="py-1.5 capitalize">{m === 'bm25' ? 'BM25 only' : m === 'vector' ? 'Vector only' : 'Hybrid (RRF)'}</td>
              <td className="py-1.5 text-right tabular">{pct(v.strict['recall@1'])}</td>
              <td className="py-1.5 text-right tabular">{pct(v.strict['recall@5'])}</td>
              <td className="py-1.5 text-right tabular">{v.strict.mrr.toFixed(2)}</td>
              <td className="py-1.5 text-right tabular text-muted">{Math.round(v.latency_ms_p50)} ms</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="grid grid-cols-2 gap-3 px-5 pt-3 pb-5 text-[13px]">
        <div className="rounded-lg bg-surface-2 p-3">
          <div className="text-[12px] text-muted">Table extraction spot check</div>
          <div className="mt-0.5 font-semibold tabular text-fg">{bench.tables?.passed}/{bench.tables?.checked} tables exact</div>
        </div>
        <div className="rounded-lg bg-surface-2 p-3">
          <div className="text-[12px] text-muted">Ingest speed</div>
          <div className="mt-0.5 font-semibold tabular text-fg">
            {bench.ingest_speed?.extract_pages_per_sec ?? '—'} pages/s · {bench.ingest_speed?.embed_chunks_per_sec ?? '—'} chunks/s
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function KnowledgeBase() {
  const toast = useToast();
  const [docs, setDocs] = useState<KbDoc[] | null>(null);
  const [stats, setStats] = useState<KbStats | null>(null);
  const [bench, setBench] = useState<KbBenchmark | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [ticker, setTicker] = useState('');
  const [mode, setMode] = useState<Mode>('hybrid');
  const [hits, setHits] = useState<KbHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [ingesting, setIngesting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, s, b] = await Promise.all([api<KbDoc[]>('/kb/docs'), api<KbStats>('/kb/stats'), api<KbBenchmark>('/kb/benchmark')]);
      setDocs(d); setStats(s); setBench(b); setError(null);
      setIngesting(s.ingest.running);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the knowledge base');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!ingesting) return;
    const t = setInterval(() => { void load(); }, 4000);
    return () => clearInterval(t);
  }, [ingesting, load]);

  const tickers = useMemo(() => [...new Set((docs ?? []).map(d => d.ticker))].sort(), [docs]);

  const runSearch = async (e?: FormEvent) => {
    e?.preventDefault();
    if (query.trim().length < 2) return;
    setSearching(true);
    try {
      const qs = new URLSearchParams({ q: query.trim(), k: '5', mode });
      if (ticker) qs.set('ticker', ticker);
      const r = await api<KbSearchResponse>(`/kb/search?${qs}`);
      setHits(r.results);
    } catch (err) {
      toast('error', 'Search failed', err instanceof Error ? err.message : undefined);
    } finally {
      setSearching(false);
    }
  };

  const startIngest = async () => {
    try {
      const r = await api<{ started: boolean; message?: string }>('/kb/ingest', { method: 'POST', body: JSON.stringify({ download: true }) });
      if (r.started) { setIngesting(true); toast('success', 'Ingest started', 'New or changed documents will be processed.'); }
      else toast('info', 'Ingest already running', r.message);
    } catch (err) {
      toast('error', 'Could not start ingest', err instanceof Error ? err.message : undefined);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <PageHeader title="Knowledge base"
        subtitle="Annual reports and earnings-call transcripts the agents cite as filings evidence"
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />Refresh</Button>
          <Button size="sm" onClick={() => void startIngest()} loading={ingesting}>{ingesting ? 'Ingesting…' : 'Sync corpus'}</Button>
        </>} />

      {error && (
        <div className="mb-4 flex gap-2 rounded-xl border border-down/25 bg-down/10 p-3 text-[13px] text-fg-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-down" />{error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Documents" icon={<FileText className="h-4 w-4" />} loading={!stats}
          value={stats ? `${stats.by_status.indexed ?? 0}/${stats.documents}` : ''} sub={<span className="text-muted">indexed · {stats?.companies.length ?? 0} companies</span>} />
        <Stat label="Pages" icon={<BookOpen className="h-4 w-4" />} loading={!stats} value={stats?.pages.toLocaleString('en-IN')}
          sub={stats && stats.scanned_pages > 0 ? <span className="text-warn">{stats.scanned_pages} scanned (no text)</span> : <span className="text-muted">all with a text layer</span>} />
        <Stat label="Chunks" icon={<Database className="h-4 w-4" />} loading={!stats} value={stats?.chunks.toLocaleString('en-IN')}
          sub={<span className="text-muted">{stats?.vectors?.toLocaleString('en-IN') ?? '—'} vectors · {stats?.vector_store ?? 'offline'}</span>} />
        <Stat label="Tables extracted" icon={<Table2 className="h-4 w-4" />} loading={!stats} value={stats?.tables.toLocaleString('en-IN')}
          sub={<span className="text-muted">as markdown</span>} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader title="Search filings" subtitle="Hybrid BM25 + vector search, the same retriever the agents use" />
          <form onSubmit={e => void runSearch(e)} className="flex flex-wrap gap-2 px-5">
            <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="e.g. gross NPA ratio March 2026"
              className="min-w-[220px] flex-1" aria-label="Search query" />
            <Select value={ticker} onChange={e => setTicker(e.target.value)} className="w-36" aria-label="Company">
              <option value="">All companies</option>
              {tickers.map(t => <option key={t} value={t}>{tickerLabel(t)}</option>)}
            </Select>
            <Button type="submit" loading={searching} disabled={query.trim().length < 2}><Search className="h-4 w-4" />Search</Button>
          </form>
          <div className="px-5 pt-3">
            <Segmented value={mode} onChange={setMode} options={[
              { value: 'hybrid', label: 'Hybrid' }, { value: 'bm25', label: 'BM25' }, { value: 'vector', label: 'Vector' }]} />
          </div>
          <div className="p-5">
            {hits === null ? (
              <EmptyState icon={<Search className="h-5 w-5" />} title="Ask the filings"
                body="Results show the passage, its page and section, and a link that opens the PDF at that page." />
            ) : hits.length === 0 ? (
              <EmptyState icon={<Search className="h-5 w-5" />} title="No matching passages" body="Try different wording or another company." />
            ) : (
              <ul className="space-y-3">{hits.map(h => <HitCard key={`${h.doc_id}:${h.page}:${h.text.slice(0, 24)}`} hit={h} />)}</ul>
            )}
          </div>
        </Card>
        <BenchmarkCard bench={bench} />
      </div>

      <Card className="mt-6">
        <CardHeader title="Documents" subtitle="Manifest-driven corpus · re-ingest is idempotent (sha256)" />
        {!docs ? <div className="space-y-2 p-5">{[0, 1, 2].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div> : docs.length === 0 ? (
          <EmptyState icon={<FileText className="h-5 w-5" />} title="No documents" body="Add entries to backend/rag/manifest_seed.json and sync." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr className="border-b border-border text-left text-[12px] text-muted">
                <th className="px-5 py-2 font-medium">Company</th><th className="px-3 py-2 font-medium">Document</th>
                <th className="px-3 py-2 font-medium">Period</th><th className="px-3 py-2 text-right font-medium">Pages</th>
                <th className="px-3 py-2 text-right font-medium">Chunks</th><th className="px-3 py-2 text-right font-medium">Tables</th>
                <th className="px-3 py-2 font-medium">Status</th><th className="px-5 py-2" />
              </tr></thead>
              <tbody>{docs.map(d => (
                <tr key={d.doc_id} className="border-b border-border last:border-0 hover:bg-surface-2/60">
                  <td className="px-5 py-2.5"><div className="font-medium text-fg">{tickerLabel(d.ticker)}</div><div className="text-[12px] text-muted">{d.company}</div></td>
                  <td className="px-3 py-2.5 text-fg-2">{TYPE_LABEL[d.doc_type] ?? d.doc_type}</td>
                  <td className="px-3 py-2.5 tabular text-fg-2">{d.period ?? d.fiscal_year}</td>
                  <td className="px-3 py-2.5 text-right tabular">{d.pages ?? '—'}</td>
                  <td className="px-3 py-2.5 text-right tabular">{d.chunks ?? '—'}</td>
                  <td className="px-3 py-2.5 text-right tabular">{d.tables ?? '—'}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={STATUS_TONE[d.status] ?? 'neutral'}>{d.status.replace('_', ' ')}</Badge>
                      {d.scanned_pages.length > 0 && (
                        <span title={`Scanned pages (no text layer, not searchable): ${d.scanned_pages.join(', ')}`}>
                          <Badge tone="warn"><AlertTriangle className="h-3 w-3" />{d.scanned_pages.length} scanned</Badge>
                        </span>
                      )}
                    </div>
                    {d.error && <div className="mt-1 max-w-xs truncate text-[11px] text-down" title={d.error}>{d.error}</div>}
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    {d.has_file ? (
                      <a href={fileUrl(`/kb/files/${d.doc_id}`)} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">PDF <ExternalLink className="h-3 w-3" /></a>
                    ) : d.page_url ? (
                      <a href={d.page_url} target="_blank" rel="noreferrer" className="text-[12px] text-muted hover:text-fg">Source page</a>
                    ) : null}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
