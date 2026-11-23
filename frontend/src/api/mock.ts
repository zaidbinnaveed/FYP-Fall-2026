/**
 * Mock implementation of the API. Everything comes from `src/fixtures/`; nothing leaves the browser.
 * Replace `mockApi` with a real HTTP client implementing `Api` when the backend exists.
 */
import { classifyOutcome, DEFAULT_MARGIN } from '../domain/outcome';
import { stableHash } from '../domain/format';
import { demoHospitals } from '../fixtures/hospitals';
import { DEMO_MODEL_VERSION, sampleRegistry, sampleThresholds } from '../fixtures/models';
import { sampleCases, sampleProbabilities } from '../fixtures/samples';
import { exampleAdherence, examplePlan, exampleReminders } from '../fixtures/treatment';
import { loadBenchmark } from './report';
import type { Api, ComparisonRow, ScreeningResult } from './types';
import { strings } from '../strings';

function copy<T>(value: T): Promise<T> {
  return Promise.resolve(structuredClone(value));
}

export const mockApi: Api = {
  login(email) {
    return copy({ name: email.trim() || strings.demoUserName, email: email.trim() });
  },

  register(name, email) {
    return copy({ name: name.trim() || strings.demoUserName, email: email.trim() });
  },

  listSampleCases() {
    return copy(sampleCases);
  },

  caseForFileName(fileName) {
    const chosen = sampleCases[stableHash(fileName) % sampleCases.length];
    if (!chosen) throw new Error('No sample cases are defined in src/fixtures/samples.ts');
    return chosen.id;
  },

  getScreeningResult(caseId) {
    const sample = sampleCases.find((c) => c.id === caseId);
    const probability = sampleProbabilities[caseId]?.dummy;
    const tau = sampleThresholds.dummy;
    if (!sample || probability === undefined || tau === undefined) return copy(null);
    const result: ScreeningResult = {
      caseId,
      caseTitle: sample.title,
      probability,
      tau,
      margin: DEFAULT_MARGIN,
      modelVersion: DEMO_MODEL_VERSION,
      outcome: classifyOutcome(probability, tau, DEFAULT_MARGIN),
    };
    return copy(result);
  },

  getComparison(caseId) {
    const probabilities = sampleProbabilities[caseId] ?? {};
    const rows: ComparisonRow[] = sampleRegistry
      .filter((m) => m.input !== 'none')
      .map((m) => {
        const probability = m.input === 'image' ? (probabilities[m.architecture] ?? null) : null;
        const tau = sampleThresholds[m.architecture] ?? null;
        return {
          architecture: m.architecture,
          name: m.name,
          family: m.family,
          probability,
          tau: probability === null ? null : tau,
          outcome:
            probability === null || tau === null
              ? null
              : classifyOutcome(probability, tau, DEFAULT_MARGIN),
        };
      });
    return copy(rows);
  },

  getBenchmark() {
    return loadBenchmark();
  },

  getRegistry() {
    return copy(sampleRegistry);
  },

  getHospitals() {
    return copy([...demoHospitals].sort((a, b) => a.distanceKm - b.distanceKm));
  },

  getTreatmentPlan() {
    return copy(examplePlan);
  },

  getReminders() {
    return copy(exampleReminders);
  },

  getAdherence() {
    return copy(exampleAdherence);
  },
};
