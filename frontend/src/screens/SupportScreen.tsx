import { Link } from 'react-router';
import { Disclaimer } from '../components/Disclaimer';
import { paths } from '../navigation';
import { strings } from '../strings';

/** UC-CHT-01 placeholder: the chatbot is on hold, so there is deliberately no message input. */
export function SupportScreen() {
  return (
    <>
      <title>{`${strings.supportHeading} — ${strings.appName}`}</title>
      <h1>{strings.supportHeading}</h1>
      <section aria-labelledby="chatbot-heading" className="placeholder-panel">
        <h2 id="chatbot-heading">{strings.chatbotHeading}</h2>
        <p>{strings.chatbotBody}</p>
      </section>
      <Disclaimer />
      <p>{strings.chatbotHelp}</p>
      <p className="actions">
        <Link to={paths.hospitals}>{strings.hospitalsLink}</Link>
        <Link to={paths.treatment}>{strings.treatmentLink}</Link>
      </p>
    </>
  );
}
