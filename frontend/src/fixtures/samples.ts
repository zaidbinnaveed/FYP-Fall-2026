/**
 * SAMPLE DATA — NOT REAL RESULTS.
 *
 * Fixed sample cases for the demo screening flow. No image is analysed: each case has preset
 * probabilities so that the three outcome bands (SRS Appendix B) can be shown.
 */
import type { SampleCase } from '../api/types';

export const sampleCases: SampleCase[] = [
  {
    id: 'case-a',
    title: 'Sample case A',
    description: 'Shows the "OSCC suspected" band.',
  },
  {
    id: 'case-b',
    title: 'Sample case B',
    description: 'Shows the "Inconclusive" band.',
  },
  {
    id: 'case-c',
    title: 'Sample case C',
    description: 'Shows the "No OSCC features detected" band.',
  },
];

/** Sample probabilities per case and per image model (architecture key). */
export const sampleProbabilities: Record<string, Record<string, number>> = {
  'case-a': {
    dummy: 0.91,
    resnet50: 0.88,
    efficientnet_b0: 0.83,
    densenet121: 0.9,
    vit_b_16: 0.86,
  },
  'case-b': {
    dummy: 0.52,
    resnet50: 0.47,
    efficientnet_b0: 0.31,
    densenet121: 0.49,
    vit_b_16: 0.55,
  },
  'case-c': {
    dummy: 0.12,
    resnet50: 0.09,
    efficientnet_b0: 0.15,
    densenet121: 0.07,
    vit_b_16: 0.2,
  },
};
