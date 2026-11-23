import { Link, NavLink, Outlet, useLocation } from 'react-router';
import { useDemoAuth } from '../auth/context';
import { flowSteps, navItems, paths } from '../navigation';
import { strings } from '../strings';

function FlowSteps() {
  const { pathname } = useLocation();
  return (
    <nav aria-label={strings.flowLabel} className="flow">
      <ol>
        {flowSteps.map((step, index) => {
          const current = step.match(pathname);
          return (
            <li key={step.key} className={current ? 'flow-step flow-step--current' : 'flow-step'}>
              <span aria-current={current ? 'step' : undefined}>
                {index + 1}. {step.label}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function Layout() {
  const { user, signOut } = useDemoAuth();
  return (
    <>
      <a className="skip-link" href="#main">
        {strings.skipToContent}
      </a>
      <header className="site-header">
        <p className="demo-banner" role="note">
          <span aria-hidden="true">⚠ </span>
          {strings.demoBanner}
        </p>
        <div className="header-row">
          <Link to={paths.home} className="app-name">
            {strings.appName}
          </Link>
          <div className="account">
            {user ? (
              <>
                <span>{strings.signedInAs(user.name)}</span>
                <button type="button" className="link-button" onClick={signOut}>
                  {strings.logOut}
                </button>
              </>
            ) : (
              <>
                <Link to={paths.login}>{strings.nav.login}</Link>
                <Link to={paths.register}>{strings.nav.register}</Link>
              </>
            )}
          </div>
        </div>
        <nav aria-label={strings.primaryNavLabel} className="primary-nav">
          <ul>
            {navItems.map((item) => (
              <li key={item.path}>
                <NavLink to={item.path}>{item.label}</NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <FlowSteps />
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <p>{strings.footer}</p>
      </footer>
    </>
  );
}
