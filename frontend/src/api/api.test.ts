import { describe, expect, it, vi } from 'vitest';
import { demoHospitals } from '../fixtures/hospitals';
import { sampleCases } from '../fixtures/samples';
import { mockApi } from './mock';
import { loadBenchmark, parseReport, REPORT_URL } from './report';

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

const REPORT = {
  generated_at: '2026-11-20T08:00:00Z',
  rows: [
    {
      architecture: 'resnet50',
      model: 'ResNet50',
      family: 'CNN',
      status: 'completed',
      run: 'x',
      auc_roc_estimate: 0.5,
      auc_roc_ci_low: 0.4,
      auc_roc_ci_high: 0.6,
      threshold: 0.3,
      parameter_count: 100,
      cpu_latency_mean_ms: 1.5,
      gpu_latency_mean_ms: null,
    },
    { architecture: 'vit_b_16', model: 'ViT-B/16', status: 'not yet run' },
  ],
  notes: ['a note'],
};

describe('research report loading', () => {
  it('parses the oscc-ml report summary.json shape', () => {
    const parsed = parseReport(REPORT);
    expect(parsed?.source).toBe('report');
    expect(parsed?.generatedAt).toBe('2026-11-20T08:00:00Z');
    expect(parsed?.rows).toHaveLength(2);
    expect(parsed?.rows[0]?.auc_roc_estimate).toBe(0.5);
    expect(parsed?.rows[1]).toEqual({
      architecture: 'vit_b_16',
      model: 'ViT-B/16',
      status: 'not yet run',
    });
    expect(parsed?.notes).toEqual(['a note']);
  });

  it.each([
    ['not an object', 'oops'],
    ['no rows', { generated_at: 'x' }],
    ['row without a model', { rows: [{ architecture: 'a', status: 's' }] }],
    [
      'non-numeric metric',
      { rows: [{ architecture: 'a', model: 'A', status: 's', threshold: '1' }] },
    ],
  ])('rejects a malformed report (%s)', (_name, raw) => {
    expect(parseReport(raw)).toBeNull();
  });

  it('fetches /report/summary.json and uses it when valid', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(REPORT));
    const benchmark = await loadBenchmark(fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith(REPORT_URL, expect.anything());
    expect(benchmark.source).toBe('report');
  });

  it.each([
    ['404', async () => new Response('missing', { status: 404 })],
    [
      'HTML fallback page',
      async () => new Response('<!doctype html>', { headers: { 'content-type': 'text/html' } }),
    ],
    ['malformed JSON document', async () => jsonResponse({ rows: 'no' })],
    ['network error', async () => Promise.reject(new TypeError('offline'))],
  ])('falls back to labelled sample data on %s', async (_name, impl) => {
    const benchmark = await loadBenchmark(vi.fn(impl));
    expect(benchmark.source).toBe('sample');
    expect(benchmark.rows.length).toBeGreaterThan(0);
  });
});

describe('mock API', () => {
  it('maps a file name to the same sample case every time', () => {
    const first = mockApi.caseForFileName('biopsy_017.png');
    expect(mockApi.caseForFileName('biopsy_017.png')).toBe(first);
    expect(sampleCases.map((c) => c.id)).toContain(first);
  });

  it('covers all three outcome bands with the sample cases', async () => {
    const outcomes = await Promise.all(
      sampleCases.map(async (c) => (await mockApi.getScreeningResult(c.id))?.outcome),
    );
    expect(outcomes).toEqual(['oscc_suspected', 'inconclusive', 'non_oscc']);
  });

  it('returns the dummy-v0 model version on every result', async () => {
    const result = await mockApi.getScreeningResult('case-a');
    expect(result?.modelVersion).toBe('dummy-v0');
    expect(result?.margin).toBe(0.05);
  });

  it('returns null for an unknown case', async () => {
    expect(await mockApi.getScreeningResult('nope')).toBeNull();
  });

  it('compares the CNN, ViT and tabular models; tabular models do not score images', async () => {
    const rows = await mockApi.getComparison('case-a');
    expect(rows.map((r) => r.name)).toEqual([
      'ResNet50',
      'EfficientNet-B0',
      'DenseNet121',
      'ViT-B/16',
      'Logistic regression',
      'Random forest',
      'Gradient boosting',
    ]);
    for (const row of rows.filter((r) => r.family === 'Tabular')) {
      expect(row.probability).toBeNull();
      expect(row.outcome).toBeNull();
    }
  });

  it('returns hospitals sorted by distance', async () => {
    const hospitals = await mockApi.getHospitals();
    const distances = hospitals.map((h) => h.distanceKm);
    expect(distances).toEqual([...distances].sort((a, b) => a - b));
  });

  it('accepts any login input', async () => {
    expect((await mockApi.login('', '')).name).toBe('Demo user');
    expect((await mockApi.login('a@b.c', 'x')).name).toBe('a@b.c');
  });
});

describe('fixture safety rules', () => {
  it('uses only fictional "Demo Hospital X" names and no phone numbers', () => {
    for (const h of demoHospitals) {
      expect(h.name).toMatch(/^Demo Hospital [A-Z]$/);
      expect(h.address).toMatch(/\(fictional\)$/);
    }
    expect(JSON.stringify(demoHospitals)).not.toMatch(/\+?\d[\d\s-]{6,}\d/);
  });
});
