import { expect, type Locator } from '@playwright/test';

// Use only after confirming table-cell/editor ownership and commit behavior in the current UI.
// Supply a row selected by a unique product/key and a stable non-editing blur target.
// The marker is the rendered value, not the click target. Its table-cell owns the editor.
export async function setNumericCell(options: {
  row: Locator;
  cellTestId: string;
  value: number;
  blurTarget: Locator;
  parse: (text: string) => number;
}) {
  const { row, cellTestId, value, blurTarget, parse } = options;
  await expect(row).toHaveCount(1);
  const marker = row.getByTestId(cellTestId);
  await expect(marker).toHaveCount(1);
  const cell = row.locator('[data-component="table-cell"]').filter({ has: row.page().getByTestId(cellTestId) });
  await expect(cell).toHaveCount(1);
  await cell.click();
  const editor = cell.getByTestId('base-edit-input');
  await expect(editor).toHaveCount(1);
  await expect(editor).toBeVisible();
  await expect(editor).toHaveAttribute('inputmode', 'decimal');
  await editor.fill(String(value));
  await expect.poll(async () => parse(await editor.inputValue())).toBe(value);
  await editor.press('Tab');
  await blurTarget.click();
  await expect(editor).toHaveCount(0);
  await expect.poll(async () => parse(await marker.innerText())).toBe(value);
}

// Locale-specific, intentionally not a universal parser.
export function parseEnUSNumber(text: string): number {
  const normalized = text.replace(/[\s,]/g, '');
  if (!/^-?\d+(\.\d+)?$/.test(normalized)) {
    throw new Error(`Unexpected en-US numeric display: ${JSON.stringify(text)}`);
  }
  return Number(normalized);
}
