import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { navItems } from './navigation';
import { strings } from './strings';
import { expectNoAxeViolations, renderApp } from './test/render';

describe('App shell', () => {
  it('renders the home page heading', async () => {
    renderApp('/');
    expect(
      screen.getByRole('heading', { level: 1, name: 'OSCC Health Intelligence' }),
    ).toBeVisible();
    await expectNoAxeViolations();
  });

  it('offers a skip link to the main landmark', () => {
    renderApp('/');
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute(
      'href',
      '#main',
    );
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  it.each(['/', '/login', '/upload', '/hospitals', '/support', '/admin', '/no-such-page'])(
    'shows the demo-mode banner on %s',
    (path) => {
      renderApp(path);
      expect(screen.getByText(strings.demoBanner)).toBeVisible();
    },
  );

  it('lists every menu item from the navigation config', () => {
    renderApp('/');
    const nav = screen.getByRole('navigation', { name: strings.primaryNavLabel });
    for (const item of navItems) {
      expect(within(nav).getByRole('link', { name: item.label })).toHaveAttribute(
        'href',
        item.path,
      );
    }
  });

  it('marks the current step of the guided flow', () => {
    renderApp('/hospitals');
    const flow = screen.getByRole('navigation', { name: strings.flowLabel });
    expect(within(flow).getByText('3. Hospitals')).toHaveAttribute('aria-current', 'step');
  });

  it('shows a not-found page for unknown routes', async () => {
    renderApp('/no-such-page');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Go to the home page' })).toHaveAttribute('href', '/');
    await expectNoAxeViolations();
  });
});
