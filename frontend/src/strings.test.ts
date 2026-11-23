import { describe, expect, it } from 'vitest';
import { examplePlan } from './fixtures/treatment';
import { strings } from './strings';

describe('user-facing wording (SRS Appendix B, CLAUDE.md safety rules)', () => {
  it('uses the exact Appendix B outcome text', () => {
    expect(strings.outcomeText).toEqual({
      oscc_suspected: 'Features suggestive of OSCC detected — medical review recommended.',
      inconclusive: 'Inconclusive — medical review recommended.',
      non_oscc:
        'No OSCC features detected by the model — this is not a diagnosis; consult a doctor if symptoms persist.',
    });
  });

  it('states the Appendix B rules', () => {
    expect(strings.outcomeRule).toEqual({
      oscc_suspected: 'p ≥ τ + m',
      inconclusive: 'τ − m ≤ p < τ + m',
      non_oscc: 'p < τ − m',
    });
  });

  it('shows the required demo banner text', () => {
    expect(strings.demoBanner).toBe('Demo mode — sample data, not a medical device');
  });

  it('contains no dose amounts anywhere in strings or the example plan', () => {
    const text = JSON.stringify(strings) + JSON.stringify(examplePlan);
    expect(text).not.toMatch(/\d+(\.\d+)?\s?(mg|ml|mcg|µg|g|tablets?|capsules?|drops?)\b/i);
  });
});
