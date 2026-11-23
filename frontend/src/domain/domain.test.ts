import { describe, expect, it } from 'vitest';
import type { Benchmark, RegistryModel } from '../api/types';
import { sampleRegistry } from '../fixtures/models';
import { strings } from '../strings';
import { hasMetrics, mergeRegistryWithBenchmark, metricText } from './benchmark';
import { formatCi, formatParams, formatPkt, stableHash } from './format';
import { MAX_UPLOAD_BYTES, validateUpload } from './upload';

describe('format helpers', () => {
  it('displays UTC timestamps in PKT (UTC+5)', () => {
    expect(formatPkt('2026-11-23T10:00:00Z')).toBe('23 Nov 2026, 15:00');
  });

  it('returns unparseable timestamps unchanged', () => {
    expect(formatPkt('not a date')).toBe('not a date');
  });

  it('formats estimates with confidence intervals', () => {
    expect(formatCi(0.9, 0.85, 0.94)).toBe('0.900 [0.850, 0.940]');
    expect(formatCi(0.9, null, 0.94)).toBe('0.900');
    expect(formatCi(null, 0.1, 0.2)).toBeNull();
  });

  it('formats parameter counts', () => {
    expect(formatParams(23_500_000)).toBe('23.5 M');
    expect(formatParams(50_000)).toBe('50.0 k');
    expect(formatParams(20)).toBe('20');
    expect(formatParams(null)).toBeNull();
  });

  it('hashes strings deterministically', () => {
    expect(stableHash('slide_01.png')).toBe(stableHash('slide_01.png'));
    expect(stableHash('a')).not.toBe(stableHash('b'));
  });
});

describe('validateUpload (UC-SCR-01 alternate 3a)', () => {
  const file = (type: string, size = 10) =>
    new File([new Uint8Array(size)], 'x', { type, lastModified: 0 });

  it('requires a file', () => {
    expect(validateUpload(null)).toBe(strings.uploadNoFile);
  });

  it('accepts JPEG, PNG and TIFF', () => {
    for (const type of ['image/jpeg', 'image/png', 'image/tiff']) {
      expect(validateUpload(file(type))).toBeNull();
    }
  });

  it('rejects other types', () => {
    expect(validateUpload(file('application/pdf'))).toBe(strings.uploadBadType);
  });

  it('rejects files over 20 MB', () => {
    const big = file('image/png');
    Object.defineProperty(big, 'size', { value: MAX_UPLOAD_BYTES + 1 });
    expect(validateUpload(big)).toBe(strings.uploadTooLarge);
  });
});

describe('mergeRegistryWithBenchmark', () => {
  const registry: RegistryModel[] = sampleRegistry.filter((m) => m.input !== 'none');

  it('marks models missing from the report as having no metrics', () => {
    const report: Benchmark = {
      source: 'report',
      generatedAt: null,
      notes: [],
      rows: [
        {
          architecture: 'resnet50',
          model: 'ResNet50',
          family: 'CNN',
          status: 'completed',
          auc_roc_estimate: 0.5,
          auc_roc_ci_low: 0.4,
          auc_roc_ci_high: 0.6,
        },
        { architecture: 'vit_b_16', model: 'ViT-B/16', status: 'not yet run' },
        { architecture: 'new_model', model: 'New model', family: 'CNN', status: 'not yet run' },
      ],
    };
    const merged = mergeRegistryWithBenchmark(registry, report);
    const byArch = Object.fromEntries(merged.map((m) => [m.architecture, m]));
    expect(hasMetrics(byArch.resnet50?.row ?? null)).toBe(true);
    expect(hasMetrics(byArch.vit_b_16?.row ?? null)).toBe(false);
    expect(hasMetrics(byArch.random_forest?.row ?? null)).toBe(false);
    expect(byArch.new_model?.name).toBe('New model');
    const resnet = byArch.resnet50?.row;
    expect(resnet && metricText(resnet, 'auc_roc')).toBe('0.500 [0.400, 0.600]');
  });
});
