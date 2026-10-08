import { useState, type ReactNode } from 'react';
import { BrainCircuit, CalendarClock, ClipboardCheck, Network, Search, Workflow } from 'lucide-react';
import { cn } from '../lib/format';
import { Badge, Card, PageHeader } from './ui';
import { InteractiveDiagram } from './architecture/Diagram';
import { KIND, type Kind } from './architecture/types';
import { intents, overview, overviewModes, pipeline } from './architecture/systemDiagrams';
import { monitor, monitorModes, news, prophet, xgboost } from './architecture/mlDiagrams';
import { evals, ragBench, ragIngest, ragModes, ragQuery, review, reviewModes } from './architecture/flowDiagrams';
import { HeadlineExamples, ProphetSlope, ScorecardSimulator, XgbCalculator } from './architecture/MlWidgets';

/**
 * How FinSight works, as interactive diagrams. Entirely static: this page makes no API calls,
 * so it works the same whether or not the backend is running.
 */
const LAST_UPDATED = '8 October 2026';

const SECTIONS = [
  { id: 'arch-overview', n: 1, title: 'System overview', icon: Network },
  { id: 'arch-pipeline', n: 2, title: 'Advisor pipeline', icon: Workflow },
  { id: 'arch-ml', n: 3, title: 'Machine learning', icon: BrainCircuit },
  { id: 'arch-rag', n: 4, title: 'Retrieval over filings', icon: Search },
  { id: 'arch-review', n: 5, title: 'Review & evaluation', icon: ClipboardCheck },
];

function Section({ id, n, title, subtitle, children }: { id: string; n: number; title: string; subtitle: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-6" aria-labelledby={`${id}-h`}>
      <Card>
        <div className="flex items-start gap-3 px-5 pt-5 pb-4">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-[13px] font-semibold text-primary tabular">{n}</span>
          <div className="min-w-0">
            <h2 id={`${id}-h`} className="text-[17px] font-semibold tracking-tight text-fg">{title}</h2>
            <div className="mt-0.5 max-w-3xl text-[13.5px] leading-relaxed text-muted">{subtitle}</div>
          </div>
        </div>
        {children}
      </Card>
    </section>
  );
}

function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="px-5 pb-2 text-[13px] font-semibold uppercase tracking-wide text-muted">{children}</h3>;
}

const LEGEND: Kind[] = ['client', 'service', 'agent', 'ml', 'data', 'external', 'person', 'output'];

const ML_TABS = [
  { id: 'score', title: 'Signal scorecard', blurb: 'Combines 9 factors into BUY / HOLD / SELL' },
  { id: 'xgb', title: 'XGBoost', blurb: 'Odds of a ±2% move in the next 5 days' },
  { id: 'prophet', title: 'Prophet', blurb: 'Direction of the long-term trend' },
  { id: 'finbert', title: 'FinBERT news', blurb: 'Tone of headlines, −1 to +1' },
  { id: 'monitor', title: 'Alert monitor', blurb: 'Rules that raise alerts every 15 min' },
] as const;
type MlTab = typeof ML_TABS[number]['id'];

export default function Architecture() {
  const [ml, setMl] = useState<MlTab>('score');
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-8 lg:px-10">
      <PageHeader title="Architecture"
        subtitle="How FinSight works, from your question to a cited, checked answer. Every diagram is interactive."
        actions={<Badge className="normal-case tracking-normal"><CalendarClock className="h-3.5 w-3.5" />Last updated {LAST_UPDATED}</Badge>} />

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Sections" className="flex flex-wrap gap-1.5">
          {SECTIONS.map(s => (
            <button key={s.id} type="button" onClick={() => jump(s.id)}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[12.5px] font-medium text-fg-2 transition-colors hover:border-border-strong hover:text-fg">
              <s.icon className="h-3.5 w-3.5 text-muted" />{s.n}. {s.title}
            </button>
          ))}
        </nav>
        <ul aria-label="Legend" className="flex flex-wrap gap-x-3 gap-y-1">
          {LEGEND.map(k => (
            <li key={k} className="flex items-center gap-1.5 text-[11.5px] text-muted">
              <span className="h-2.5 w-2.5 rounded-[3px] border" style={{ background: `color-mix(in oklab, ${KIND[k].color} 18%, var(--surface))`, borderColor: KIND[k].color, borderStyle: k === 'external' ? 'dashed' : 'solid' }} />
              {KIND[k].label}
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-6">
        <Section id="arch-overview" n={1} title="System overview"
          subtitle="Everything runs on one AWS EC2 server with Docker Compose. Only the web server is reachable from the internet; the database, Redis and backend sit on a private Docker network.">
          <InteractiveDiagram spec={overview} label="System overview diagram" modes={overviewModes} modesLabel="Follow a request"
            intro={<p>Three things happen here: you <b className="text-fg">ask the advisor</b> (left to top), <b className="text-fg">live prices</b> stream in, and <b className="text-fg">news turns into alerts</b> (right side). Pick one above to watch it step by step.</p>} />
        </Section>

        <Section id="arch-pipeline" n={2} title="Advisor pipeline"
          subtitle="A LangGraph graph of LLM agents. The specialist agents run in parallel, every fact they find becomes numbered evidence, the verdict comes from fixed rules rather than the LLM, and a validator checks the draft before you see it.">
          <InteractiveDiagram spec={pipeline} label="Advisor pipeline diagram" modes={intents} modesLabel="Question type" initialMode="research"
            intro={<p>The orchestrator decides which agents a question needs. Pick a question type to see which path it takes.</p>} />
        </Section>

        <Section id="arch-ml" n={3} title="Machine learning"
          subtitle="Five models and rule engines feed the advisor and the alerts. The ML outputs never decide on their own: each becomes one weighted, explained factor. Filing search embeddings are covered in section 4.">
          <div className="grid grid-cols-2 gap-2 px-5 pb-4 sm:grid-cols-3 lg:grid-cols-5" role="tablist" aria-label="Machine learning component">
            {ML_TABS.map(t => (
              <button key={t.id} type="button" role="tab" aria-selected={ml === t.id} onClick={() => setMl(t.id)}
                className={cn('rounded-xl border px-3 py-2.5 text-left transition-colors duration-150',
                  ml === t.id ? 'border-primary/40 bg-primary/[0.07]' : 'border-border bg-surface hover:border-border-strong')}>
                <div className={cn('text-[13px] font-semibold', ml === t.id ? 'text-primary' : 'text-fg')}>{t.title}</div>
                <div className="mt-0.5 text-[11.5px] leading-snug text-muted">{t.blurb}</div>
              </button>
            ))}
          </div>
          <div key={ml} className="animate-fade-in">
            {ml === 'score' && (
              <div className="px-5 pb-5">
                <p className="mb-4 max-w-3xl text-[13px] leading-relaxed text-fg-2">
                  The scoring engine turns raw tool outputs into factor scores from −1 to +1 and combines them with fixed weights. The LLM is given the result and must explain it; it cannot change it. Move the sliders to see how the verdict responds.
                </p>
                <ScorecardSimulator />
              </div>
            )}
            {ml === 'xgb' && (
              <InteractiveDiagram spec={xgboost} label="XGBoost signal pipeline"
                intro={<p>A small gradient-boosted tree model trained on the fly for each stock asked about. Its vote in the verdict is scaled by how well it did on data it had not seen.</p>}
                footer={() => <div className="mt-5 border-t border-border pt-5"><XgbCalculator /></div>} />
            )}
            {ml === 'prophet' && (
              <InteractiveDiagram spec={prophet} label="Prophet trend pipeline"
                intro={<p>Prophet separates the long-term trend from short-term wiggles. Only the direction of that trend is used.</p>}
                footer={() => <div className="mt-5 border-t border-border pt-5"><ProphetSlope /></div>} />
            )}
            {ml === 'finbert' && (
              <InteractiveDiagram spec={news} label="News sentiment pipeline"
                intro={<p>Headlines are matched to companies by name, scored by FinBERT and averaged over 7 days. Every score can be traced back to the articles behind it.</p>}
                footer={() => <div className="mt-5 border-t border-border pt-5"><HeadlineExamples /></div>} />
            )}
            {ml === 'monitor' && (
              <InteractiveDiagram spec={monitor} label="Alert monitor rules" modes={monitorModes} modesLabel="Alert type"
                intro={<p>Every 15 minutes in market hours, every holding is checked against four kinds of rule. Each alert says which articles or data it was raised on.</p>} />
            )}
          </div>
        </Section>

        <Section id="arch-rag" n={4} title="Retrieval over filings (RAG)"
          subtitle="Annual reports and earnings-call transcripts are indexed so the Research Agent can quote what a company itself reports, with the exact page.">
          <SubHeading>Ingest: done once, re-run when documents change</SubHeading>
          <InteractiveDiagram spec={ragIngest} label="Filing ingest pipeline"
            intro={<p>PDFs become page-accurate chunks that are indexed twice: as vectors (meaning) and as keywords (exact words and numbers).</p>} />
          <div className="border-t border-border pt-5" />
          <SubHeading>Search: every time the agent asks</SubHeading>
          <InteractiveDiagram spec={ragQuery} label="Hybrid filing search" modes={ragModes} modesLabel="Retriever" initialMode="hybrid"
            intro={<p>Two rankings of the same chunks are fused, so a passage that either one finds can make the top five.</p>}
            footer={modeId => (
              <div className="mt-4">
                <div className="overflow-x-auto rounded-xl border border-border">
                  <table className="w-full min-w-[480px] text-[13px]">
                    <caption className="px-3 pt-2.5 pb-1 text-left text-[12px] text-muted">Benchmark: 34 questions with hand-checked answer pages, top 5 results, as of the last update. Higher is better.</caption>
                    <thead>
                      <tr className="text-left text-[12px] text-muted">
                        <th className="px-3 py-2 font-medium">Retriever</th>
                        <th className="px-3 py-2 text-right font-medium" title="Right page ranked first">Recall@1</th>
                        <th className="px-3 py-2 text-right font-medium" title="Right page anywhere in the top 5">Recall@5</th>
                        <th className="px-3 py-2 text-right font-medium" title="Mean reciprocal rank">MRR</th>
                        <th className="px-3 py-2 text-right font-medium">Typical time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ragBench.map(b => {
                        const best = (k: 'r1' | 'r5' | 'mrr') => Math.max(...ragBench.map(x => x[k])) === b[k];
                        return (
                          <tr key={b.id} className={cn('border-t border-border transition-colors', modeId === b.id && 'bg-primary/[0.07]')}>
                            <td className={cn('px-3 py-2 font-medium', modeId === b.id ? 'text-primary' : 'text-fg')}>{b.name}{b.id === 'hybrid' && <span className="ml-2 text-[11px] font-normal text-muted">used by the app</span>}</td>
                            {(['r1', 'r5', 'mrr'] as const).map(k => (
                              <td key={k} className={cn('px-3 py-2 text-right tabular', best(k) ? 'font-semibold text-fg' : 'text-fg-2')}>{b[k].toFixed(2)}</td>
                            ))}
                            <td className="px-3 py-2 text-right text-fg-2 tabular">{b.ms}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )} />
        </Section>

        <Section id="arch-review" n={5} title="Review, learning loop & evaluation"
          subtitle="An analyst can correct any answer in plain English. Approved corrections are published and feed back into later answers, and a separate harness measures answer quality and signal value.">
          <SubHeading>Expert review and approval</SubHeading>
          <InteractiveDiagram spec={review} label="Expert review workflow" modes={reviewModes} modesLabel="Follow a correction"
            intro={<p>Corrections are handled by the cheapest reliable method first: rules, then a check against the evidence, and only then an LLM. Pick a correction above to follow it.</p>} />
          <div className="border-t border-border pt-5" />
          <SubHeading>Evaluation harness</SubHeading>
          <InteractiveDiagram spec={evals} label="Evaluation harness"
            intro={<p>Two separate questions: are the answers well-formed and grounded in their evidence (top), and does the scorecard actually predict anything (bottom)? Results appear on the Evaluation page.</p>} />
        </Section>
      </div>

      <p className="mt-8 text-center text-[12px] text-muted">Diagrams describe the system as of {LAST_UPDATED}. Figures marked “as of the last update” are measurements from that time.</p>
    </div>
  );
}
