/**
 * Screening outcome mapping (SRS Appendix B, CLAUDE.md section 3).
 *
 *   oscc_suspected  if p ≥ τ + m
 *   inconclusive    if τ − m ≤ p < τ + m
 *   non_oscc        if p < τ − m
 *
 * The bounds are computed as `tau + margin` and `tau - margin`, exactly as written in the rule.
 */
export const OUTCOMES = ['oscc_suspected', 'inconclusive', 'non_oscc'] as const;
export type Outcome = (typeof OUTCOMES)[number];

/** Default inconclusive margin m (plan decision O3). */
export const DEFAULT_MARGIN = 0.05;

function assertUnitInterval(name: string, value: number): void {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new RangeError(`${name} must be a number between 0 and 1, got ${value}`);
  }
}

export function classifyOutcome(probability: number, tau: number, margin: number): Outcome {
  assertUnitInterval('probability', probability);
  assertUnitInterval('tau', tau);
  if (!Number.isFinite(margin) || margin < 0) {
    throw new RangeError(`margin must be a non-negative number, got ${margin}`);
  }
  if (probability >= tau + margin) return 'oscc_suspected';
  if (probability >= tau - margin) return 'inconclusive';
  return 'non_oscc';
}
