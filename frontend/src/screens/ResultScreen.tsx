import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useParams } from 'react-router';
import { api } from '../api';
import { Disclaimer } from '../components/Disclaimer';
import { OutcomeBadge } from '../components/OutcomeBadge';
import { SourceBadge } from '../components/SourceBadge';
import { comparePath, paths } from '../navigation';
import { strings } from '../strings';

function fileNameFromState(state: unknown): string | null {
  if (typeof state === 'object' && state !== null && 'fileName' in state) {
    const { fileName } = state as { fileName: unknown };
    return typeof fileName === 'string' ? fileName : null;
  }
  return null;
}

/** UC-SCR-02: outcome with label + icon, p, τ, m, model version, Appendix B text, disclaimer. */
export function ResultScreen() {
  const { caseId = '' } = useParams();
  const fileName = fileNameFromState(useLocation().state);
  const result = useQuery({
    queryKey: ['result', caseId],
    queryFn: () => api.getScreeningResult(caseId),
  });

  const title = <title>{`${strings.resultHeading} — ${strings.appName}`}</title>;

  if (result.isPending) {
    return (
      <>
        {title}
        <h1>{strings.resultHeading}</h1>
        <p>{strings.loading}</p>
      </>
    );
  }

  const data = result.data;
  if (!data) {
    return (
      <>
        {title}
        <h1>{strings.resultHeading}</h1>
        <p role="alert">{strings.resultNotFound}</p>
        <Link to={paths.upload}>{strings.newScreening}</Link>
      </>
    );
  }

  const referral = data.outcome !== 'non_oscc';

  return (
    <>
      {title}
      <h1>{strings.resultHeading}</h1>
      <p className="note">
        {fileName
          ? strings.resultFromFile(fileName, data.caseTitle)
          : strings.resultFromSample(data.caseTitle)}
      </p>

      <section
        className={`result-panel result-panel--${data.outcome}`}
        aria-labelledby="outcome-heading"
      >
        <h2 id="outcome-heading" className="result-outcome">
          <OutcomeBadge outcome={data.outcome} large />
        </h2>
        <p className="outcome-text" data-testid="outcome-text">
          {strings.outcomeText[data.outcome]}
        </p>
        <p>
          <SourceBadge source="sample" />
        </p>
        <dl className="facts">
          <div>
            <dt>{strings.probabilityLabel}</dt>
            <dd>{data.probability.toFixed(2)}</dd>
          </div>
          <div>
            <dt>{strings.thresholdLabel}</dt>
            <dd>{data.tau.toFixed(2)}</dd>
          </div>
          <div>
            <dt>{strings.marginLabel}</dt>
            <dd>{data.margin.toFixed(2)}</dd>
          </div>
          <div>
            <dt>{strings.outcomeRuleLabel}</dt>
            <dd>{strings.outcomeRule[data.outcome]}</dd>
          </div>
          <div>
            <dt>{strings.modelVersionLabel}</dt>
            <dd>{data.modelVersion}</dd>
          </div>
        </dl>
      </section>

      <Disclaimer />

      <section aria-labelledby="explanation-heading">
        <h2 id="explanation-heading">{strings.explanationHeading}</h2>
        <div className="explanation-placeholder" data-testid="explanation-placeholder">
          <p>{strings.explanationPlaceholder}</p>
        </div>
      </section>

      <p className="actions">
        {referral ? (
          <Link className="button" to={paths.hospitals}>
            {strings.findHospitalsPrompt}
          </Link>
        ) : (
          <Link to={paths.hospitals}>{strings.hospitalsLink}</Link>
        )}
        <Link to={paths.support}>{strings.supportLink}</Link>
        <Link to={comparePath(data.caseId)}>{strings.compareLink}</Link>
        <Link to={paths.upload}>{strings.newScreening}</Link>
      </p>
    </>
  );
}
