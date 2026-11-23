import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { strings } from '../strings';
import { expectNoAxeViolations, renderApp } from '../test/render';

describe('Nearest hospitals (UC-HOS-01..03, fictional data)', () => {
  it('lists fictional demo hospitals with straight-line distances', async () => {
    renderApp('/hospitals');
    const names = (await screen.findAllByRole('heading', { level: 2 })).map((h) => h.textContent);
    expect(names).toEqual([
      'Demo Hospital A',
      'Demo Hospital B',
      'Demo Hospital C',
      'Demo Hospital D',
      'Demo Hospital E',
    ]);
    expect(screen.getByText(strings.distanceLabel('2.4'))).toBeVisible();
    expect(screen.getByText(strings.hospitalsDemoNote)).toBeVisible();
    expect(document.querySelector('a[href^="tel:"]')).toBeNull();
    await expectNoAxeViolations();
  });

  it('filters by facility type (UC-HOS-02)', async () => {
    renderApp('/hospitals');
    await screen.findByText('Demo Hospital A');
    fireEvent.click(screen.getByLabelText(strings.facilityType.oncology_center));
    expect(screen.queryByText('Demo Hospital A')).toBeNull();
    expect(screen.getByText('Demo Hospital C')).toBeVisible();
  });

  it('says so when no hospital matches (alternate: empty result)', async () => {
    renderApp('/hospitals');
    await screen.findByText('Demo Hospital A');
    for (const label of Object.values(strings.facilityType)) {
      fireEvent.click(screen.getByLabelText(label));
    }
    expect(screen.getByRole('status')).toHaveTextContent(strings.noHospitals);
    await expectNoAxeViolations();
  });

  it('shows details without a phone number (UC-HOS-03)', async () => {
    renderApp('/hospitals');
    await screen.findByText('Demo Hospital A');
    expect(screen.getAllByText(strings.phoneNotInDemo)).toHaveLength(5);
  });

  it('continues to support', async () => {
    renderApp('/hospitals');
    expect(await screen.findByRole('link', { name: strings.continueToSupport })).toHaveAttribute(
      'href',
      '/support',
    );
  });
});
