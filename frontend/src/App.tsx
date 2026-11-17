import { Link, Route, Routes } from 'react-router';
import { strings } from './strings';

function Home() {
  return (
    <>
      <h1>{strings.homeHeading}</h1>
      <p>{strings.homeStatus}</p>
    </>
  );
}

function NotFound() {
  return (
    <>
      <h1>{strings.notFoundHeading}</h1>
      <p>{strings.notFoundBody}</p>
      <Link to="/">{strings.backHome}</Link>
    </>
  );
}

export function App() {
  return (
    <>
      <a className="skip-link" href="#main">
        {strings.skipToContent}
      </a>
      <header>
        <span>{strings.appName}</span>
      </header>
      <main id="main" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  );
}
