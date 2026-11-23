import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { api } from '../api';
import { OutcomeBadge } from '../components/OutcomeBadge';
import { SourceBadge } from '../components/SourceBadge';
import { hasMetrics, mergeRegistryWithBenchmark, metricText } from '../domain/benchmark';
import { strings } from '../strings';

/** UC-SCR-03: CNN, ViT and tabular models side by side. */
export function CompareScreen() {
  const [params, setParams] = useSearchParams();
  const cases = useQuery({ queryKey: ['sample-cases'], queryFn: () => api.listSampleCases() });
  const caseId = params.get('case') ?? cases.data?.[0]?.id ?? '';
  const comparison = useQuery({
    queryKey: ['comparison', caseId],
    queryFn: () => api.getComparison(caseId),
    enabled: caseId !== '',
  });
  const registry = useQuery({ queryKey: ['registry'], queryFn: () => api.getRegistry() });
  const benchmark = useQuery({ queryKey: ['benchmark'], queryFn: () => api.getBenchmark() });

  const models =
    registry.data && benchmark.data
      ? mergeRegistryWithBenchmark(
          registry.data.filter((m) => m.input !== 'none'),
          benchmark.data,
        )
      : null;

  return (
    <>
      <title>{`${strings.compareHeading} — ${strings.appName}`}</title>
      <h1>{strings.compareHeading}</h1>
      <p>{strings.compareIntro}</p>

      <div className="form inline">
        <label htmlFor="compare-case">{strings.compareCaseLabel}</label>
        <select
          id="compare-case"
          value={caseId}
          onChange={(e) => setParams({ case: e.target.value })}
        >
          {(cases.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
      </div>

      <h2>{strings.comparePredictionsHeading}</h2>
      {comparison.data ? (
        <div className="table-wrap">
          <table>
            <caption>
              <SourceBadge source="sample" />
            </caption>
            <thead>
              <tr>
                <th scope="col">{strings.colModel}</th>
                <th scope="col">{strings.colFamily}</th>
                <th scope="col">{strings.colProbability}</th>
                <th scope="col">{strings.colThreshold}</th>
                <th scope="col">{strings.colOutcome}</th>
              </tr>
            </thead>
            <tbody>
              {comparison.data.map((row) => (
                <tr key={row.architecture}>
                  <th scope="row">{row.name}</th>
                  <td>{row.family}</td>
                  <td>
                    {row.probability === null ? strings.notApplicable : row.probability.toFixed(2)}
                  </td>
                  <td>{row.tau === null ? strings.notApplicable : row.tau.toFixed(2)}</td>
                  <td>
                    {row.outcome ? <OutcomeBadge outcome={row.outcome} /> : strings.notApplicable}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>{strings.loading}</p>
      )}
      <p className="note">{strings.tabularNote}</p>

      <h2>{strings.compareMetricsHeading}</h2>
      {models && benchmark.data ? (
        <div className="table-wrap">
          <table>
            <caption>
              <SourceBadge
                source={benchmark.data.source}
                generatedAt={benchmark.data.generatedAt}
              />
            </caption>
            <thead>
              <tr>
                <th scope="col">{strings.colModel}</th>
                <th scope="col">{strings.colFamily}</th>
                <th scope="col">{strings.colAuc}</th>
                <th scope="col">{strings.colRecall}</th>
                <th scope="col">{strings.colSpecificity}</th>
                <th scope="col">{strings.colF1}</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.architecture}>
                  <th scope="row">{m.name}</th>
                  <td>{m.family}</td>
                  {hasMetrics(m.row) ? (
                    <>
                      <td>{metricText(m.row, 'auc_roc') ?? strings.notApplicable}</td>
                      <td>{metricText(m.row, 'recall') ?? strings.notApplicable}</td>
                      <td>{metricText(m.row, 'specificity') ?? strings.notApplicable}</td>
                      <td>{metricText(m.row, 'f1') ?? strings.notApplicable}</td>
                    </>
                  ) : (
                    <td colSpan={4}>{strings.notYetRun}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>{strings.loading}</p>
      )}
    </>
  );
}
