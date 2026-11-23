import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { api } from '../api';
import { useDemoAuth } from '../auth/context';
import { paths } from '../navigation';
import { strings } from '../strings';

/** UC-USR-02 (mock): any input is accepted. */
export function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { signIn } = useDemoAuth();
  const navigate = useNavigate();

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    signIn(await api.login(email, password));
    await navigate(paths.upload);
  }

  return (
    <>
      <title>{`${strings.loginHeading} — ${strings.appName}`}</title>
      <h1>{strings.loginHeading}</h1>
      <p className="note">{strings.authDemoNote}</p>
      <form className="form" onSubmit={(e) => void onSubmit(e)}>
        <label htmlFor="login-email">{strings.emailLabel}</label>
        <input
          id="login-email"
          type="email"
          autoComplete="off"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="login-password">{strings.passwordLabel}</label>
        <input
          id="login-password"
          type="password"
          autoComplete="off"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="button">
          {strings.loginSubmit}
        </button>
      </form>
      <p>
        {strings.noAccount} <Link to={paths.register}>{strings.nav.register}</Link>
      </p>
    </>
  );
}

/** UC-USR-01 (mock): any input is accepted. */
export function RegisterScreen() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { signIn } = useDemoAuth();
  const navigate = useNavigate();

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    signIn(await api.register(name, email, password));
    await navigate(paths.upload);
  }

  return (
    <>
      <title>{`${strings.registerHeading} — ${strings.appName}`}</title>
      <h1>{strings.registerHeading}</h1>
      <p className="note">{strings.authDemoNote}</p>
      <form className="form" onSubmit={(e) => void onSubmit(e)}>
        <label htmlFor="register-name">{strings.nameLabel}</label>
        <input
          id="register-name"
          type="text"
          autoComplete="off"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <label htmlFor="register-email">{strings.emailLabel}</label>
        <input
          id="register-email"
          type="email"
          autoComplete="off"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="register-password">{strings.passwordLabel}</label>
        <input
          id="register-password"
          type="password"
          autoComplete="off"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="button">
          {strings.registerSubmit}
        </button>
      </form>
      <p>
        {strings.haveAccount} <Link to={paths.login}>{strings.nav.login}</Link>
      </p>
    </>
  );
}
