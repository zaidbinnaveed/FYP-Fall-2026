import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { strings } from '../strings';
import { expectNoAxeViolations, renderApp } from '../test/render';

describe('Support / chatbot placeholder (UC-CHT-01, on hold)', () => {
  it('shows "coming soon" with the disclaimer and no way to send a message', async () => {
    renderApp('/support');
    expect(screen.getByRole('heading', { name: strings.chatbotHeading })).toBeVisible();
    expect(screen.getByTestId('disclaimer')).toHaveTextContent(strings.disclaimer);
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(document.querySelector('main form, main input, main textarea')).toBeNull();
    expect(screen.queryByRole('button', { name: /send/i })).toBeNull();
    await expectNoAxeViolations();
  });
});
