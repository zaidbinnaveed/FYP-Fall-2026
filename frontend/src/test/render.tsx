import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import axe from 'axe-core';
import { MemoryRouter } from 'react-router';
import { expect } from 'vitest';
import { App } from '../App';

/** Renders the whole app (layout + landmarks) at a route, with fresh providers. */
export function renderApp(path: string, state?: unknown) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: pathOf(path), search: searchOf(path), state }]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function pathOf(path: string): string {
  const index = path.indexOf('?');
  return index === -1 ? path : path.slice(0, index);
}

function searchOf(path: string): string {
  const index = path.indexOf('?');
  return index === -1 ? '' : path.slice(index);
}

/**
 * Runs axe-core on the rendered document and fails on any violation. Colour contrast cannot be
 * computed in jsdom (no layout or CSS); it is checked in the Playwright run instead.
 */
export async function expectNoAxeViolations(): Promise<void> {
  const results = await axe.run(document.body, {
    rules: { 'color-contrast': { enabled: false } },
  });
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join('; ')})`,
  );
  expect(summary).toEqual([]);
}

/** Narrows `T | null | undefined` to `T` in tests, failing loudly instead of using `!`. */
export function defined<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('expected a value');
  return value;
}
