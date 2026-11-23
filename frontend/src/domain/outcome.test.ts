import { describe, expect, it } from 'vitest';
import { classifyOutcome, DEFAULT_MARGIN } from './outcome';

describe('classifyOutcome (SRS Appendix B)', () => {
  const tau = 0.5;
  const m = DEFAULT_MARGIN;

  it('uses the default margin m = 0.05 (plan decision O3)', () => {
    expect(DEFAULT_MARGIN).toBe(0.05);
  });

  it('is oscc_suspected exactly at p = τ + m (closed lower bound)', () => {
    expect(classifyOutcome(tau + m, tau, m)).toBe('oscc_suspected');
  });

  it('is inconclusive just below τ + m', () => {
    expect(classifyOutcome(tau + m - 1e-9, tau, m)).toBe('inconclusive');
  });

  it('is inconclusive exactly at p = τ − m (closed lower bound)', () => {
    expect(classifyOutcome(tau - m, tau, m)).toBe('inconclusive');
  });

  it('is non_oscc just below τ − m', () => {
    expect(classifyOutcome(tau - m - 1e-9, tau, m)).toBe('non_oscc');
  });

  it('is inconclusive at p = τ', () => {
    expect(classifyOutcome(tau, tau, m)).toBe('inconclusive');
  });

  it('handles the extremes 0 and 1', () => {
    expect(classifyOutcome(0, tau, m)).toBe('non_oscc');
    expect(classifyOutcome(1, tau, m)).toBe('oscc_suspected');
  });

  it('works with other thresholds and margins', () => {
    expect(classifyOutcome(0.47, 0.42, 0.05)).toBe('oscc_suspected');
    expect(classifyOutcome(0.37, 0.42, 0.05)).toBe('inconclusive');
    expect(classifyOutcome(0.369, 0.42, 0.05)).toBe('non_oscc');
  });

  it('has no inconclusive band when m = 0', () => {
    expect(classifyOutcome(0.5, 0.5, 0)).toBe('oscc_suspected');
    expect(classifyOutcome(0.4999, 0.5, 0)).toBe('non_oscc');
  });

  it.each([
    [Number.NaN, 0.5, 0.05],
    [-0.1, 0.5, 0.05],
    [1.1, 0.5, 0.05],
    [0.5, 1.5, 0.05],
    [0.5, 0.5, -0.01],
    [0.5, 0.5, Number.POSITIVE_INFINITY],
  ])('rejects invalid input p=%s τ=%s m=%s', (p, t, margin) => {
    expect(() => classifyOutcome(p, t, margin)).toThrow(RangeError);
  });
});
