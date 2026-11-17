import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { App } from './App';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe('App shell', () => {
  it('renders the home page heading', () => {
    renderAt('/');
    expect(
      screen.getByRole('heading', { level: 1, name: 'OSCC Health Intelligence' }),
    ).toBeVisible();
  });

  it('offers a skip link to the main landmark', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute(
      'href',
      '#main',
    );
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  it('shows a not-found page for unknown routes', () => {
    renderAt('/no-such-page');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Go to the home page' })).toHaveAttribute('href', '/');
  });
});
