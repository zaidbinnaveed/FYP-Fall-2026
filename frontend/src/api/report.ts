/**
 * Loads the research report produced by `oscc-ml report` (copied to `public/report/summary.json`
 * by `npm run sync-report`). When it is missing or malformed, sample fixtures are used and the UI
 * says so ("Sample data — not real results").
 */
import { sampleBenchmarkRows } from '../fixtures/models';
import type { Benchmark, BenchmarkRow } from './types';

export const REPORT_URL = '/report/summary.json';

const NUMERIC_FIELDS = [
  'auc_roc_estimate',
  'auc_roc_ci_low',
  'auc_roc_ci_high',
  'recall_estimate',
  'recall_ci_low',
  'recall_ci_high',
  'specificity_estimate',
  'specificity_ci_low',
  'specificity_ci_high',
  'f1_estimate',
  'f1_ci_low',
  'f1_ci_high',
  'threshold',
  'parameter_count',
  'cpu_latency_mean_ms',
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseRow(raw: unknown): BenchmarkRow | null {
  if (!isRecord(raw)) return null;
  const { architecture, model, status, family } = raw;
  if (typeof architecture !== 'string' || typeof model !== 'string' || typeof status !== 'string') {
    return null;
  }
  const row: BenchmarkRow = { architecture, model, status };
  if (typeof family === 'string') row.family = family;
  for (const field of NUMERIC_FIELDS) {
    const value = raw[field];
    if (value === undefined || value === null) continue;
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    row[field] = value;
  }
  return row;
}

/** Returns `null` when the document does not have the summary.json shape. */
export function parseReport(raw: unknown): Benchmark | null {
  if (!isRecord(raw) || !Array.isArray(raw.rows)) return null;
  const rows: BenchmarkRow[] = [];
  for (const item of raw.rows) {
    const row = parseRow(item);
    if (row === null) return null;
    rows.push(row);
  }
  const notes = Array.isArray(raw.notes)
    ? raw.notes.filter((n): n is string => typeof n === 'string')
    : [];
  return {
    source: 'report',
    generatedAt: typeof raw.generated_at === 'string' ? raw.generated_at : null,
    rows,
    notes,
  };
}

export function sampleBenchmark(): Benchmark {
  return {
    source: 'sample',
    generatedAt: null,
    rows: structuredClone(sampleBenchmarkRows),
    notes: [],
  };
}

export async function loadBenchmark(fetchImpl: typeof fetch = fetch): Promise<Benchmark> {
  try {
    const response = await fetchImpl(REPORT_URL, { cache: 'no-store' });
    if (!response.ok) return sampleBenchmark();
    // The dev server answers unknown paths with index.html; only accept JSON.
    const type = response.headers.get('content-type') ?? '';
    if (!type.includes('json')) return sampleBenchmark();
    return parseReport(await response.json()) ?? sampleBenchmark();
  } catch {
    return sampleBenchmark();
  }
}
