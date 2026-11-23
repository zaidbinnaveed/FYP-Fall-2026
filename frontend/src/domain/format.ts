/** Display helpers. Timestamps are stored in UTC and displayed in PKT (CLAUDE.md section 3). */

const PKT = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Karachi',
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export function formatPkt(isoUtc: string): string {
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return isoUtc;
  return PKT.format(date);
}

export function formatNumber(value: number | null | undefined, digits = 3): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return value.toFixed(digits);
}

export function formatCi(
  estimate: number | null | undefined,
  low: number | null | undefined,
  high: number | null | undefined,
): string | null {
  const est = formatNumber(estimate);
  if (est === null) return null;
  const lo = formatNumber(low);
  const hi = formatNumber(high);
  return lo === null || hi === null ? est : `${est} [${lo}, ${hi}]`;
}

export function formatParams(count: number | null | undefined): string | null {
  if (count === null || count === undefined || !Number.isFinite(count)) return null;
  if (count >= 1e6) return `${(count / 1e6).toFixed(1)} M`;
  if (count >= 1e3) return `${(count / 1e3).toFixed(1)} k`;
  return String(count);
}

/** Deterministic, non-cryptographic string hash (used only to pick a demo fixture by file name). */
export function stableHash(text: string): number {
  let hash = 0;
  for (const char of text) {
    hash = (hash * 31 + (char.codePointAt(0) ?? 0)) >>> 0;
  }
  return hash;
}
