import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { strings } from '../strings';
import { expectNoAxeViolations, renderApp } from '../test/render';

function chooseFile(file: File) {
  fireEvent.change(screen.getByLabelText(strings.uploadFileLabel), { target: { files: [file] } });
  fireEvent.click(screen.getByRole('button', { name: strings.uploadSubmit }));
}

describe('Upload (UC-SCR-01, mock)', () => {
  it('offers a file input and the three sample cases', async () => {
    renderApp('/upload');
    expect(screen.getByRole('heading', { level: 1, name: strings.uploadHeading })).toBeVisible();
    expect(await screen.findByRole('link', { name: 'Use Sample case A' })).toHaveAttribute(
      'href',
      '/result/case-a',
    );
    expect(screen.getByRole('link', { name: 'Use Sample case B' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Use Sample case C' })).toBeVisible();
    await expectNoAxeViolations();
  });

  it('asks for a file when none is chosen', async () => {
    renderApp('/upload');
    fireEvent.click(screen.getByRole('button', { name: strings.uploadSubmit }));
    expect(await screen.findByRole('alert')).toHaveTextContent(strings.uploadNoFile);
    await expectNoAxeViolations();
  });

  it('rejects an unsupported file type (alternate 3a)', async () => {
    renderApp('/upload');
    chooseFile(new File(['x'], 'notes.pdf', { type: 'application/pdf' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(strings.uploadBadType);
  });

  it('rejects a file over 20 MB (alternate 3a)', async () => {
    renderApp('/upload');
    const big = new File(['x'], 'big.png', { type: 'image/png' });
    Object.defineProperty(big, 'size', { value: 20 * 1024 * 1024 + 1 });
    chooseFile(big);
    expect(await screen.findByRole('alert')).toHaveTextContent(strings.uploadTooLarge);
  });

  it('shows a sample result for a valid image and says no model was run', async () => {
    renderApp('/upload');
    chooseFile(new File(['x'], 'slide.png', { type: 'image/png' }));
    expect(await screen.findByText(/the file "slide\.png" was not analysed/)).toBeVisible();
    expect(screen.getByRole('heading', { level: 1, name: strings.resultHeading })).toBeVisible();
  });
});
