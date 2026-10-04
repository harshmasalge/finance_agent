import { ExternalLink, FileText } from 'lucide-react';
import { API_URL } from '../../lib/api';
import { Badge } from '../ui';
import type { SearchFilingsOutput } from './types';

const TYPE_LABEL: Record<string, string> = { annual_report: 'Annual report', earnings_call: 'Earnings call' };

/** True when an evidence output came from the `search_filings` tool. */
export function isFilingsOutput(o: unknown): o is SearchFilingsOutput {
  return !!o && typeof o === 'object' && Array.isArray((o as SearchFilingsOutput).passages);
}

/** Renders `search_filings` evidence (prefix F) in the Sources panel: one card per passage with
 *  document, page, section, the quoted text and an "Open PDF" link that jumps to the page. */
export default function FilingPassages({ output }: { output: SearchFilingsOutput }) {
  if (!output.passages.length) {
    return <p className="text-[13px] text-muted">{output.message ?? 'No passage matched this query.'}</p>;
  }
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-muted">Query: <span className="text-fg-2">“{output.query}”</span></div>
      <ul className="space-y-2">
        {output.passages.map((p, i) => (
          <li key={`${p.doc_id}:${p.page}:${i}`} className="rounded-lg border border-border p-2.5 transition-colors hover:border-border-strong">
            <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
              <FileText className="h-3.5 w-3.5 text-muted" />
              <span className="font-medium text-fg">{p.title}</span>
              <Badge>{TYPE_LABEL[p.doc_type] ?? p.doc_type}</Badge>
              <span className="text-muted">p. {p.page}</span>
              <a href={`${API_URL}${p.url}`} target="_blank" rel="noreferrer"
                className="ml-auto inline-flex items-center gap-1 font-medium text-primary hover:underline">
                Open PDF <ExternalLink className="h-3 w-3" />
              </a>
            </div>
            {p.section && <div className="mt-0.5 truncate text-[11px] text-muted" title={p.section}>{p.section}</div>}
            <blockquote className="mt-1.5 line-clamp-6 whitespace-pre-line border-l-2 border-border-strong pl-2.5 text-[12.5px] leading-relaxed text-fg-2">
              {p.text}
            </blockquote>
          </li>
        ))}
      </ul>
    </div>
  );
}
