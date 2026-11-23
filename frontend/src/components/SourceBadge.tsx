import type { DataSource } from '../api/types';
import { formatPkt } from '../domain/format';
import { strings } from '../strings';

/** Says where numbers come from: the research report (run folders) or sample fixtures. */
export function SourceBadge({
  source,
  generatedAt = null,
}: {
  source: DataSource;
  generatedAt?: string | null;
}) {
  if (source === 'report') {
    return (
      <span className="source source--report" data-source="report">
        <span aria-hidden="true">✓ </span>
        {strings.sourceReport}
        {generatedAt ? ` — ${strings.reportGeneratedAt(formatPkt(generatedAt))}` : ''}
      </span>
    );
  }
  return (
    <span className="source source--sample" data-source="sample">
      <span aria-hidden="true">⚠ </span>
      {strings.sourceSample}
    </span>
  );
}
