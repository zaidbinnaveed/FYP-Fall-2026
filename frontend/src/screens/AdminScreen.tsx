import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { SourceBadge } from '../components/SourceBadge';
import {
  hasMetrics,
  latencyText,
  mergeRegistryWithBenchmark,
  metricText,
  paramsText,
  thresholdText,
} from '../domain/benchmark';
import { strings } from '../strings';

/** UC-ADM-03 (mock): model registry with benchmark metrics; shows which model is active. */
export function AdminScreen() {
  const registry = useQuery({ queryKey: ['registry'], queryFn: () => api.getRegistry() });
  const benchmark = useQuery({ queryKey: ['benchmark'], queryFn: () => api.getBenchmark() });
  const na = strings.notApplicable;

  return (
    <>
      <title>{`${strings.adminHeading} — ${strings.appName}`}</title>
      <h1>{strings.adminHeading}</h1>
      <p className="note">{strings.adminNote}</p>

      <h2>{strings.registryHeading}</h2>
      {registry.data && benchmark.data ? (
        <>
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
                  <th scope="col">{strings.colStatus}</th>
                  <th scope="col">{strings.colActive}</th>
                  <th scope="col">{strings.colAuc}</th>
                  <th scope="col">{strings.colRecall}</th>
                  <th scope="col">{strings.colThreshold}</th>
                  <th scope="col">{strings.colParams}</th>
                  <th scope="col">{strings.colLatency}</th>
                </tr>
              </thead>
              <tbody>
                {mergeRegistryWithBenchmark(registry.data, benchmark.data).map((m) => {
                  const active = m.registry?.status === 'active';
                  const isDemo = m.registry?.input === 'none';
                  return (
                    <tr key={m.architecture} className={active ? 'row--active' : undefined}>
                      <th scope="row">
                        {m.name}
                        {m.registry && <span className="muted"> ({m.registry.version})</span>}
                      </th>
                      <td>{m.family}</td>
                      <td>{m.registry ? strings.registryStatus[m.registry.status] : na}</td>
                      <td>
                        {active ? (
                          <strong>
                            <span aria-hidden="true">★ </span>
                            {strings.activeYes}
                          </strong>
                        ) : (
                          <>
                            <span aria-hidden="true">{strings.activeNo}</span>
                            <span className="visually-hidden">{strings.notActive}</span>
                          </>
                        )}
                      </td>
                      {hasMetrics(m.row) ? (
                        <>
                          <td>{metricText(m.row, 'auc_roc') ?? na}</td>
                          <td>{metricText(m.row, 'recall') ?? na}</td>
                          <td>{thresholdText(m.row) ?? na}</td>
                          <td>{paramsText(m.row) ?? na}</td>
                          <td>{latencyText(m.row) ?? na}</td>
                        </>
                      ) : (
                        <td colSpan={5}>{isDemo ? na : strings.notYetRun}</td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="note">{strings.dummyModelNote}</p>
          {benchmark.data.notes.length > 0 && (
            <>
              <h2>{strings.reportNotes}</h2>
              <ul>
                {benchmark.data.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : (
        <p>{strings.loading}</p>
      )}
    </>
  );
}
