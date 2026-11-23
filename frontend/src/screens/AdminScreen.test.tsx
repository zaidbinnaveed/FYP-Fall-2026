import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import { strings } from '../strings';
import { defined, expectNoAxeViolations, renderApp } from '../test/render';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Admin benchmark and model registry (UC-ADM-03, mock)', () => {
  it('shows the registry with the active model and sample-data label', async () => {
    renderApp('/admin');
    const table = await screen.findByRole('table');
    expect(within(table).getByText(strings.sourceSample)).toBeVisible();
    const active = within(table)
      .getByRole('rowheader', { name: /Demo model/ })
      .closest('tr');
    // Registry status column and the Active column both say "Active".
    expect(within(defined(active)).getAllByText(strings.activeYes)).toHaveLength(2);
    for (const col of [
      strings.colModel,
      strings.colFamily,
      strings.colStatus,
      strings.colAuc,
      strings.colRecall,
      strings.colThreshold,
      strings.colParams,
      strings.colLatency,
    ]) {
      expect(within(table).getByRole('columnheader', { name: col })).toBeVisible();
    }
    const resnet = within(table)
      .getByRole('rowheader', { name: /ResNet50/ })
      .closest('tr');
    expect(within(defined(resnet)).getByText('0.900 [0.850, 0.940]')).toBeVisible();
    await expectNoAxeViolations();
  });

  it('uses the research report when present and marks missing runs "not yet run"', async () => {
    vi.spyOn(api, 'getBenchmark').mockResolvedValue({
      source: 'report',
      generatedAt: '2026-11-20T08:00:00Z',
      notes: ['Only seed 42.'],
      rows: [
        {
          architecture: 'resnet50',
          model: 'ResNet50',
          family: 'CNN',
          status: 'completed',
          auc_roc_estimate: 0.111,
          auc_roc_ci_low: 0.1,
          auc_roc_ci_high: 0.2,
        },
        { architecture: 'vit_b_16', model: 'ViT-B/16', status: 'not yet run' },
      ],
    });
    renderApp('/admin');
    const table = await screen.findByRole('table');
    expect(
      within(table).getByText(new RegExp(`^${strings.sourceReport} — Report generated`)),
    ).toBeVisible();
    expect(within(table).queryByText(strings.sourceSample)).toBeNull();
    expect(within(table).getByText('0.111 [0.100, 0.200]')).toBeVisible();
    const vit = within(table)
      .getByRole('rowheader', { name: /ViT-B\/16/ })
      .closest('tr');
    expect(within(defined(vit)).getByText(strings.notYetRun)).toBeVisible();
    expect(screen.getByText('Only seed 42.')).toBeVisible();
    await expectNoAxeViolations();
  });
});
