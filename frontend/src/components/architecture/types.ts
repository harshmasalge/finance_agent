import type { ReactNode } from 'react';

export type Kind = 'client' | 'infra' | 'service' | 'agent' | 'ml' | 'data' | 'external' | 'process' | 'person' | 'output';

export const KIND: Record<Kind, { label: string; color: string }> = {
  client: { label: 'Front end', color: 'var(--primary)' },
  infra: { label: 'Infrastructure', color: 'var(--fg-2)' },
  service: { label: 'Backend service', color: 'var(--primary)' },
  agent: { label: 'LLM agent', color: 'var(--arch-violet)' },
  ml: { label: 'ML / scoring', color: 'var(--arch-teal)' },
  data: { label: 'Data store', color: 'var(--warn)' },
  external: { label: 'External service', color: 'var(--muted)' },
  process: { label: 'Processing step', color: 'var(--muted)' },
  person: { label: 'Person', color: 'var(--up)' },
  output: { label: 'Result', color: 'var(--up)' },
};

export interface DNode {
  id: string;
  x: number; y: number; w: number; h: number;
  title: string;
  /** One or more lines under the title ("\n" separates lines). */
  sub?: string;
  kind: Kind;
  summary: string;
  points?: string[];
}

export interface DEdge {
  from: string; to: string;
  /** Route of the arrow in diagram units, first point at the source, last at the target. */
  pts: [number, number][];
  label?: string;
  lp?: [number, number];
  anchor?: 'start' | 'middle' | 'end';
  dashed?: boolean;
  both?: boolean;
}

export interface DGroup { x: number; y: number; w: number; h: number; label: string; lx?: number; ly?: number }

export interface Spec {
  width: number; height: number; minWidth?: number;
  nodes: DNode[]; edges: DEdge[]; groups?: DGroup[];
}

export interface Step { title: string; text: string; nodes: string[]; edges?: string[] }

export interface Mode {
  id: string;
  label: string;
  summary?: ReactNode;
  nodes?: string[];
  edges?: string[];
  /** Edges shown as "possible" (lighter) while this mode is active. */
  past?: string[];
  steps?: Step[];
}

export type Hi = { nodes: Partial<Record<string, 'on' | 'past'>>; edges: Partial<Record<string, 'on' | 'past'>> } | null;

export const edgeId = (e: { from: string; to: string }) => `${e.from}>${e.to}`;
