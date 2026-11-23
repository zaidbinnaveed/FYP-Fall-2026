import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { strings } from '../strings';
import { defined, expectNoAxeViolations, renderApp } from '../test/render';

describe('Treatment plan and reminders (UC-MED-01..03, mock)', () => {
  it('shows the plan as entered, the no-advice note and the disclaimer', async () => {
    renderApp('/treatment');
    expect(await screen.findAllByText('Example medicine A')).not.toHaveLength(0);
    expect(screen.getByText(strings.treatmentNote)).toBeVisible();
    expect(screen.getByTestId('disclaimer')).toBeVisible();
    expect(await screen.findByText(strings.adherenceSummary(17, 21))).toBeVisible();
    await expectNoAxeViolations();
  });

  it('adds an entry exactly as the user typed it', async () => {
    renderApp('/treatment');
    await screen.findAllByText('Example medicine A');
    fireEvent.change(screen.getByLabelText(strings.medicineLabel), {
      target: { value: 'My medicine' },
    });
    fireEvent.change(screen.getByLabelText(strings.doseLabel), {
      target: { value: 'what my doctor wrote' },
    });
    fireEvent.change(screen.getByLabelText(strings.timeLabel), { target: { value: '21:30' } });
    fireEvent.click(screen.getByRole('button', { name: strings.addEntry }));
    expect(screen.getAllByText('My medicine')).toHaveLength(2); // plan + reminders
    expect(screen.getByText(/what my doctor wrote/)).toBeVisible();
    expect(screen.getAllByText('21:30', { selector: 'td' })).toHaveLength(2);
  });

  it('refuses an incomplete entry (alternate: missing fields)', async () => {
    renderApp('/treatment');
    await screen.findAllByText('Example medicine A');
    fireEvent.click(screen.getByRole('button', { name: strings.addEntry }));
    expect(screen.getByRole('alert')).toHaveTextContent(strings.entryMissing);
  });

  it('records a reminder response (UC-MED-02)', async () => {
    renderApp('/treatment');
    const button = await screen.findByRole('button', {
      name: `${strings.markTaken}: Example mouthwash B 13:00`,
    });
    const row = button.closest('tr');
    fireEvent.click(button);
    expect(within(defined(row)).getByText(strings.reminderStatus.taken)).toBeVisible();
    expect(within(defined(row)).queryByRole('button')).toBeNull();
  });
});
