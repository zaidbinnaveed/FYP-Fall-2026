/**
 * SAMPLE DATA — NOT REAL RESULTS.
 *
 * Model registry and benchmark numbers used when `public/report/summary.json` is absent.
 * They exist only so the screens can be reviewed. The UI labels every place they appear with
 * "Sample data — not real results". Real numbers come only from `oscc-ml report`
 * (see `npm run sync-report`).
 */
import type { BenchmarkRow, RegistryModel } from '../api/types';

export const DEMO_MODEL_VERSION = 'dummy-v0';

export const sampleRegistry: RegistryModel[] = [
  {
    architecture: 'dummy',
    name: 'Demo model',
    family: 'Demo',
    version: DEMO_MODEL_VERSION,
    status: 'active',
    input: 'none',
  },
  {
    architecture: 'resnet50',
    name: 'ResNet50',
    family: 'CNN',
    version: 'resnet50-sample',
    status: 'registered',
    input: 'image',
  },
  {
    architecture: 'efficientnet_b0',
    name: 'EfficientNet-B0',
    family: 'CNN',
    version: 'efficientnet_b0-sample',
    status: 'registered',
    input: 'image',
  },
  {
    architecture: 'densenet121',
    name: 'DenseNet121',
    family: 'CNN',
    version: 'densenet121-sample',
    status: 'registered',
    input: 'image',
  },
  {
    architecture: 'vit_b_16',
    name: 'ViT-B/16',
    family: 'ViT',
    version: 'vit_b_16-sample',
    status: 'registered',
    input: 'image',
  },
  {
    architecture: 'logistic_regression',
    name: 'Logistic regression',
    family: 'Tabular',
    version: 'logistic_regression-sample',
    status: 'registered',
    input: 'tabular',
  },
  {
    architecture: 'random_forest',
    name: 'Random forest',
    family: 'Tabular',
    version: 'random_forest-sample',
    status: 'registered',
    input: 'tabular',
  },
  {
    architecture: 'gradient_boosting',
    name: 'Gradient boosting',
    family: 'Tabular',
    version: 'gradient_boosting-sample',
    status: 'registered',
    input: 'tabular',
  },
];

/** Sample thresholds τ (per model) and the demo model's τ. */
export const sampleThresholds: Record<string, number> = {
  dummy: 0.5,
  resnet50: 0.42,
  efficientnet_b0: 0.38,
  densenet121: 0.45,
  vit_b_16: 0.4,
  logistic_regression: 0.5,
  random_forest: 0.5,
  gradient_boosting: 0.5,
};

function sampleRow(
  architecture: string,
  model: string,
  family: string,
  auc: [number, number, number],
  recall: [number, number, number],
  specificity: [number, number, number],
  f1: [number, number, number],
  parameterCount: number,
  cpuLatencyMs: number,
): BenchmarkRow {
  return {
    architecture,
    model,
    family,
    status: 'sample',
    auc_roc_estimate: auc[0],
    auc_roc_ci_low: auc[1],
    auc_roc_ci_high: auc[2],
    recall_estimate: recall[0],
    recall_ci_low: recall[1],
    recall_ci_high: recall[2],
    specificity_estimate: specificity[0],
    specificity_ci_low: specificity[1],
    specificity_ci_high: specificity[2],
    f1_estimate: f1[0],
    f1_ci_low: f1[1],
    f1_ci_high: f1[2],
    threshold: sampleThresholds[architecture] ?? null,
    parameter_count: parameterCount,
    cpu_latency_mean_ms: cpuLatencyMs,
  };
}

export const sampleBenchmarkRows: BenchmarkRow[] = [
  sampleRow(
    'resnet50',
    'ResNet50',
    'CNN',
    [0.9, 0.85, 0.94],
    [0.95, 0.9, 0.98],
    [0.7, 0.62, 0.78],
    [0.86, 0.81, 0.9],
    23_500_000,
    80,
  ),
  sampleRow(
    'efficientnet_b0',
    'EfficientNet-B0',
    'CNN',
    [0.88, 0.83, 0.92],
    [0.95, 0.9, 0.98],
    [0.65, 0.57, 0.73],
    [0.84, 0.79, 0.88],
    4_000_000,
    30,
  ),
  sampleRow(
    'densenet121',
    'DenseNet121',
    'CNN',
    [0.89, 0.84, 0.93],
    [0.95, 0.9, 0.98],
    [0.68, 0.6, 0.76],
    [0.85, 0.8, 0.89],
    7_000_000,
    60,
  ),
  sampleRow(
    'vit_b_16',
    'ViT-B/16',
    'ViT',
    [0.9, 0.85, 0.94],
    [0.95, 0.9, 0.98],
    [0.66, 0.58, 0.74],
    [0.85, 0.8, 0.89],
    85_800_000,
    150,
  ),
  sampleRow(
    'logistic_regression',
    'Logistic regression',
    'Tabular',
    [0.75, 0.68, 0.82],
    [0.9, 0.84, 0.95],
    [0.5, 0.42, 0.58],
    [0.75, 0.69, 0.8],
    20,
    1,
  ),
  sampleRow(
    'random_forest',
    'Random forest',
    'Tabular',
    [0.8, 0.74, 0.86],
    [0.9, 0.84, 0.95],
    [0.55, 0.47, 0.63],
    [0.77, 0.71, 0.82],
    50_000,
    2,
  ),
  sampleRow(
    'gradient_boosting',
    'Gradient boosting',
    'Tabular',
    [0.8, 0.74, 0.86],
    [0.9, 0.84, 0.95],
    [0.56, 0.48, 0.64],
    [0.78, 0.72, 0.83],
    10_000,
    2,
  ),
];
