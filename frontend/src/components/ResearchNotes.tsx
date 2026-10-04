import { useCallback, useEffect, useState, type ReactElement } from 'react';
import { Copy, Download, FileText, RefreshCw } from 'lucide-react';
import { api } from '../lib/api';
import { cn, tickerLabel, timeAgo } from '../lib/format';
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from './ui';
import { useToast } from './toast';
import type { NoteDetail, NoteSummary } from './review/types';

const VERDICT_TONE = { BUY: 'up', SELL: 'down', HOLD: 'warn' } as const;
const CONNECTOR_TONE = { published: 'up', received: 'primary', pending: 'neutral', failed: 'down' } as const;

function download(name: string, text: string, type = 'text/markdown') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Minimal Markdown renderer for our own note format (headings, bullets, tables, quotes, bold). */
function NoteMarkdown({ md }: { md: string }) {
  const blocks: ReactElement[] = [];
  const lines = md.split('\n');
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => p.startsWith('**') && p.endsWith('**') ? <strong key={i} className="font-semibold text-fg">{p.slice(2, -2)}</strong> : p);
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.startsWith('# ')) continue; // title shown in the header
    if (l.startsWith('## ')) blocks.push(<h4 key={i} className="mt-5 mb-2 text-[12px] font-semibold uppercase tracking-wider text-muted">{l.slice(3)}</h4>);
    else if (l.startsWith('> ')) blocks.push(<p key={i} className="border-l-2 border-primary/40 pl-3 text-[13.5px] italic text-muted">{l.slice(2)}</p>);
    else if (l.startsWith('- ')) {
      const items = [];
      while (i < lines.length && lines[i].startsWith('- ')) items.push(lines[i++].slice(2));
      i--;
      blocks.push(<ul key={i} className="space-y-1.5">{items.map((t, k) => <li key={k} className="flex gap-2.5 text-[14px] leading-relaxed text-fg-2"><span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-muted" /><span>{inline(t)}</span></li>)}</ul>);
    } else if (l.startsWith('|')) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith('|')) rows.push(lines[i++]);
      i--;
      const cells = rows.filter(r => !/^\|[-:|\s]+\|$/.test(r)).map(r => r.slice(1, -1).split('|').map(c => c.trim()));
      blocks.push(
        <div key={i} className="overflow-x-auto"><table className="w-full text-[12.5px]">
          <thead><tr>{cells[0].map((c, k) => <th key={k} className={cn('border-b border-border py-1.5 pr-3 text-left font-medium text-muted', (k === 1 || k === 2) && 'text-right')}>{c}</th>)}</tr></thead>
          <tbody>{cells.slice(1).map((r, k) => <tr key={k} className="border-b border-border/60">{r.map((c, j) => <td key={j} className={cn('py-1.5 pr-3 text-fg-2', (j === 1 || j === 2) && 'text-right tabular')}>{c}</td>)}</tr>)}</tbody>
        </table></div>);
    } else if (l.trim()) blocks.push(<p key={i} className="text-[14px] leading-relaxed text-fg-2">{inline(l)}</p>);
  }
  return <div className="space-y-2">{blocks}</div>;
}

/** Research Notes: approved, analyst-reviewed answers published through the platform connector. */
export default function ResearchNotes() {
  const toast = useToast();
  const [notes, setNotes] = useState<NoteSummary[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<NoteDetail | null>(null);

  const fetchNotes = useCallback(() => api<NoteSummary[]>('/research-notes')
    .then(n => { setNotes(n); setSelected(s => s ?? n[0]?.id ?? null); })
    .catch(e => { setNotes([]); toast('error', 'Could not load notes', (e as Error).message); }), [toast]);
  useEffect(() => { fetchNotes(); }, [fetchNotes]);
  const refresh = () => { setNotes(null); fetchNotes(); };

  useEffect(() => {
    if (selected == null) return;
    let alive = true;
    api<NoteDetail>(`/research-notes/${selected}`).then(d => { if (alive) setDetail(d); })
      .catch(e => toast('error', 'Could not load note', (e as Error).message));
    return () => { alive = false; };
  }, [selected, toast]);
  const shownDetail = detail && detail.id === selected ? detail : null;

  const slug = (d: NoteDetail) => `${(d.ticker ? tickerLabel(d.ticker) : 'note').toLowerCase()}-v${d.version}-note-${d.id}`;

  return (
    <div className="mx-auto max-w-6xl p-6 lg:p-8">
      <PageHeader title="Research Notes" subtitle="Answers approved by an analyst and published through the notes connector."
        actions={<Button variant="outline" size="sm" onClick={refresh}><RefreshCw className="h-3.5 w-3.5" />Refresh</Button>} />
      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        <Card className="overflow-hidden">
          {notes === null ? <div className="space-y-2 p-4">{[0, 1, 2].map(i => <Skeleton key={i} className="h-14" />)}</div>
            : notes.length === 0 ? (
              <EmptyState icon={<FileText className="h-5 w-5" />} title="No published notes yet"
                body="Open an answer in the AI Advisor, review it, then Approve to publish it here." />
            ) : (
              <ul className="divide-y divide-border">
                {notes.map(n => (
                  <li key={n.id}>
                    <button onClick={() => setSelected(n.id)}
                      className={cn('w-full px-4 py-3 text-left transition-colors', selected === n.id ? 'bg-primary/[0.07]' : 'hover:bg-surface-2')}>
                      <div className="flex items-center gap-2">
                        {n.ticker && <span className="text-[13px] font-semibold text-fg">{tickerLabel(n.ticker)}</span>}
                        {n.verdict && <Badge tone={VERDICT_TONE[n.verdict]}>{n.verdict}</Badge>}
                        <span className="ml-auto text-[11px] text-muted">v{n.version}</span>
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-[12.5px] text-fg-2">{n.title}</p>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                        <Badge tone={CONNECTOR_TONE[n.connector_status]} className="normal-case">{n.connector_status}</Badge>
                        {timeAgo(n.published_at)}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
        </Card>

        <Card className="min-h-[300px] p-6">
          {!shownDetail ? (notes && notes.length > 0 ? <Skeleton className="h-40" /> : null) : (
            <article className="animate-fade-in">
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <h2 className="text-lg font-semibold tracking-tight text-fg">{shownDetail.title}</h2>
                  <p className="mt-1 text-[12.5px] text-muted">
                    Note #{shownDetail.id} · message {shownDetail.message_id} · v{shownDetail.version} · {shownDetail.published_at ? `published ${timeAgo(shownDetail.published_at)}` : shownDetail.connector_status}
                    {shownDetail.connector_response?.target ? ` · target ${String(shownDetail.connector_response.target)}` : ''}
                  </p>
                </div>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline" onClick={() => { navigator.clipboard?.writeText(shownDetail.markdown); toast('success', 'Markdown copied'); }}>
                    <Copy className="h-3.5 w-3.5" />Copy
                  </Button>
                  <Button size="sm" onClick={() => download(`${slug(shownDetail)}.md`, shownDetail.markdown)}><Download className="h-3.5 w-3.5" />Export Markdown</Button>
                </div>
              </div>
              <div className="mt-4 border-t border-border pt-2"><NoteMarkdown md={shownDetail.markdown} /></div>
            </article>
          )}
        </Card>
      </div>
    </div>
  );
}
