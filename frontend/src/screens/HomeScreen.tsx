import { Link } from 'react-router';
import { paths } from '../navigation';
import { strings } from '../strings';

export function HomeScreen() {
  return (
    <>
      <title>{strings.appName}</title>
      <h1>{strings.homeHeading}</h1>
      <p>{strings.homeIntro}</p>
      <p className="note">{strings.homeDemoNote}</p>
      <p className="actions">
        <Link className="button" to={paths.login}>
          {strings.homeStart}
        </Link>
        <Link to={paths.upload}>{strings.homeSkipLogin}</Link>
      </p>
    </>
  );
}

export function NotFoundScreen() {
  return (
    <>
      <title>{`${strings.notFoundHeading} — ${strings.appName}`}</title>
      <h1>{strings.notFoundHeading}</h1>
      <p>{strings.notFoundBody}</p>
      <Link to={paths.home}>{strings.backHome}</Link>
    </>
  );
}
