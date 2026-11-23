import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { strings } from '../strings';
import { defined, expectNoAxeViolations, renderApp } from '../test/render';

const MODELS = [
  'ResNet50',
  'EfficientNet-B0',
  'DenseNet121',
  'ViT-B/16',
  'Logistic regression',
  'Random forest',
  'Gradient boosting',
];

describe('Compare models (UC-SCR-03)', () => {
  it('lists CNN, ViT and tabular models side by side with sample labels', async () => {
    renderApp('/compare?case=case-a');
    const tables = await screen.findAllByRole('table');
    expect(tables).toHaveLength(2);
    const [predictions, metrics] = tables;
    for (const name of MODELS) {
      expect(within(defined(predictions)).getByRole('rowheader', { name })).toBeVisible();
      expect(within(defined(metrics)).getByRole('rowheader', { name })).toBeVisible();
    }
    // Predictions are always sample data; metrics fall back to sample data without a report.
    expect(within(defined(predictions)).getByText(strings.sourceSample)).toBeVisible();
    expect(within(defined(metrics)).getByText(strings.sourceSample)).toBeVisible();
    await expectNoAxeViolations();
  });

  it('shows n/a for tabular models on an image case', async () => {
    renderApp('/compare?case=case-a');
    const [predictions] = await screen.findAllByRole('table');
    const row = within(defined(predictions))
      .getByRole('rowheader', { name: 'Random forest' })
      .closest('tr');
    expect(row).not.toBeNull();
    expect(within(defined(row)).getAllByText(strings.notApplicable).length).toBeGreaterThanOrEqual(
      2,
    );
  });

  it('switches the sample case', async () => {
    renderApp('/compare?case=case-a');
    await screen.findAllByRole('table');
    expect(screen.getAllByText(strings.outcomeLabel.oscc_suspected).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText(strings.compareCaseLabel), {
      target: { value: 'case-c' },
    });
    expect(await screen.findAllByText(strings.outcomeLabel.non_oscc)).toHaveLength(4);
  });
});
