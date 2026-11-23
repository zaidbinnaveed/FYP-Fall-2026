import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { strings } from '../strings';
import { expectNoAxeViolations, renderApp } from '../test/render';

describe('Login (UC-USR-02, mock)', () => {
  it('says it is a demo and has labelled fields', async () => {
    renderApp('/login');
    expect(screen.getByRole('heading', { level: 1, name: strings.loginHeading })).toBeVisible();
    expect(screen.getByText(strings.authDemoNote)).toBeVisible();
    expect(screen.getByLabelText(strings.emailLabel)).toBeVisible();
    expect(screen.getByLabelText(strings.passwordLabel)).toBeVisible();
    await expectNoAxeViolations();
  });

  it('accepts any input and continues to upload', async () => {
    renderApp('/login');
    fireEvent.change(screen.getByLabelText(strings.emailLabel), { target: { value: 'x@y.z' } });
    fireEvent.click(screen.getByRole('button', { name: strings.loginSubmit }));
    expect(
      await screen.findByRole('heading', { level: 1, name: strings.uploadHeading }),
    ).toBeVisible();
    expect(screen.getByText(strings.signedInAs('x@y.z'))).toBeVisible();
  });

  it('accepts empty input too (alternate: nothing entered)', async () => {
    renderApp('/login');
    fireEvent.click(screen.getByRole('button', { name: strings.loginSubmit }));
    expect(await screen.findByText(strings.signedInAs(strings.demoUserName))).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: strings.logOut }));
    expect(screen.getByRole('link', { name: strings.nav.login })).toBeVisible();
  });
});

describe('Register (UC-USR-01, mock)', () => {
  it('creates a demo account from any input', async () => {
    renderApp('/register');
    await expectNoAxeViolations();
    fireEvent.change(screen.getByLabelText(strings.nameLabel), { target: { value: 'Ayesha' } });
    fireEvent.click(screen.getByRole('button', { name: strings.registerSubmit }));
    expect(await screen.findByText(strings.signedInAs('Ayesha'))).toBeVisible();
  });
});
