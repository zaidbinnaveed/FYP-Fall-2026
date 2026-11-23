import { strings } from '../strings';

/** Non-diagnostic disclaimer (NFR-SAF-01): on every result and on the chatbot screen. */
export function Disclaimer() {
  return (
    <p className="disclaimer" role="note" data-testid="disclaimer">
      <strong>{strings.disclaimerHeading}:</strong> {strings.disclaimer}
    </p>
  );
}
