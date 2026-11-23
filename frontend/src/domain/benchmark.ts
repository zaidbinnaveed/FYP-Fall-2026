/** Joins the model registry with benchmark rows (from the report or sample fixtures). */
import type { Benchmark, BenchmarkRow, RegistryModel } from '../api/types';
import { formatCi, formatNumber, formatParams } from './format';

export const NOT_YET_RUN = 'not yet run';

export interface ModelWithMetrics {
  architecture: string;
  name: string;
  family: string;
  registry: RegistryModel | null;
  /** `null` when the source has no row for this model. */
  row: BenchmarkRow | null;
}

export function mergeRegistryWithBenchmark(
  registry: RegistryModel[],
  benchmark: Benchmark,
): ModelWithMetrics[] {
  const byArch = new Map(benchmark.rows.map((r) => [r.architecture, r]));
  const merged: ModelWithMetrics[] = registry.map((m) => ({
    architecture: m.architecture,
    name: m.name,
    family: m.family,
    registry: m,
    row: byArch.get(m.architecture) ?? null,
  }));
  for (const row of benchmark.rows) {
    if (!registry.some((m) => m.architecture === row.architecture)) {
      merged.push({
        architecture: row.architecture,
        name: row.model,
        family: row.family ?? '',
        registry: null,
        row,
      });
    }
  }
  return merged;
}

export function hasMetrics(row: BenchmarkRow | null): row is BenchmarkRow {
  return row !== null && row.status !== NOT_YET_RUN && row.auc_roc_estimate != null;
}

export type MetricName = 'auc_roc' | 'recall' | 'specificity' | 'f1';

/** Text for a metric cell; `null` when there is no value. */
export function metricText(row: BenchmarkRow, metric: MetricName): string | null {
  return formatCi(row[`${metric}_estimate`], row[`${metric}_ci_low`], row[`${metric}_ci_high`]);
}

export function thresholdText(row: BenchmarkRow): string | null {
  return formatNumber(row.threshold, 2);
}

export function paramsText(row: BenchmarkRow): string | null {
  return formatParams(row.parameter_count);
}

export function latencyText(row: BenchmarkRow): string | null {
  return formatNumber(row.cpu_latency_mean_ms, 1);
}
