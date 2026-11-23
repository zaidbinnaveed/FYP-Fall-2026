import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Outcome } from '../domain/outcome';
import { strings } from '../strings';
import { expectNoAxeViolations, renderApp } from '../test/render';

const CASES: [string, Outcome, string][] = [
  ['case-a', 'oscc_suspected', '0.91'],
  ['case-b', 'inconclusive', '0.52'],
  ['case-c', 'non_oscc', '0.12'],
];

describe('Result (UC-SCR-02)', () => {
  it.each(CASES)(
    '%s shows %s with label, icon, numbers and exact wording',
    async (id, outcome, p) => {
      renderApp(`/result/${id}`);
      const heading = await screen.findByRole('heading', {
        level: 2,
        name: strings.outcomeLabel[outcome],
      });
      expect(heading.querySelector(`svg[data-icon="${outcome}"]`)).not.toBeNull();
      expect(screen.getByTestId('outcome-text')).toHaveTextContent(strings.outcomeText[outcome]);
      expect(screen.getByText(strings.probabilityLabel).nextElementSibling).toHaveTextContent(p);
      expect(screen.getByText(strings.thresholdLabel).nextElementSibling).toHaveTextContent('0.50');
      expect(screen.getByText(strings.marginLabel).nextElementSibling).toHaveTextContent('0.05');
      expect(screen.getByText(strings.outcomeRuleLabel).nextElementSibling).toHaveTextContent(
        strings.outcomeRule[outcome],
      );
      expect(screen.getByText('dummy-v0')).toBeVisible();
      expect(screen.getByTestId('disclaimer')).toHaveTextContent(strings.disclaimer);
      expect(screen.getByText(strings.sourceSample)).toBeVisible();
      expect(screen.getByTestId('explanation-placeholder')).toHaveTextContent(
        strings.explanationPlaceholder,
      );
      await expectNoAxeViolations();
    },
  );

  it.each(['case-a', 'case-b'])('%s prompts the user to find hospitals', async (id) => {
    renderApp(`/result/${id}`);
    expect(await screen.findByRole('link', { name: strings.findHospitalsPrompt })).toHaveAttribute(
      'href',
      '/hospitals',
    );
  });

  it('non_oscc offers hospital search as a plain link', async () => {
    renderApp('/result/case-c');
    expect(await screen.findByRole('link', { name: strings.hospitalsLink })).toHaveAttribute(
      'href',
      '/hospitals',
    );
    expect(screen.queryByRole('link', { name: strings.findHospitalsPrompt })).toBeNull();
  });

  it('says it is a fixed sample result', async () => {
    renderApp('/result/case-a');
    expect(await screen.findByText(strings.resultFromSample('Sample case A'))).toBeVisible();
  });

  it('handles an unknown case', async () => {
    renderApp('/result/does-not-exist');
    expect(await screen.findByRole('alert')).toHaveTextContent(strings.resultNotFound);
    await expectNoAxeViolations();
  });
});
