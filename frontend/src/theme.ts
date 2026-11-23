/**
 * Design tokens: colours and spacing in one place. They are applied as CSS custom properties
 * (`--color-…`, `--space-…`) on the document root by `applyTheme()` and used by `index.css`.
 * Text/background pairs below meet WCAG 2.1 AA contrast (≥ 4.5:1); change them in pairs.
 */
export const theme = {
  color: {
    text: '#1a1a1a',
    textMuted: '#4a4a4a',
    background: '#ffffff',
    surface: '#f5f7fa',
    border: '#8a94a6',
    primary: '#1a4fa0',
    primaryText: '#ffffff',
    focus: '#1a4fa0',
    bannerBackground: '#fff4d6',
    bannerText: '#4d3800',
    bannerBorder: '#b38600',
    sampleBackground: '#fde8e8',
    sampleText: '#7a1414',
    reportBackground: '#e3f1e6',
    reportText: '#1d5e2c',
    errorText: '#a11a1a',
    // Outcome colours are never the only carrier of meaning: every outcome also has a label and an icon.
    suspectedBackground: '#fdecec',
    suspectedText: '#8c1616',
    inconclusiveBackground: '#fff4dc',
    inconclusiveText: '#6b4200',
    nonOsccBackground: '#e6f4ea',
    nonOsccText: '#1d5e2c',
  },
  space: {
    xs: '0.25rem',
    sm: '0.5rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem',
  },
  radius: '6px',
  maxWidth: '72rem',
} as const;

function kebab(name: string): string {
  return name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
}

export function themeVariables(): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const [key, value] of Object.entries(theme.color)) vars[`--color-${kebab(key)}`] = value;
  for (const [key, value] of Object.entries(theme.space)) vars[`--space-${key}`] = value;
  vars['--radius'] = theme.radius;
  vars['--max-width'] = theme.maxWidth;
  return vars;
}

export function applyTheme(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(themeVariables())) {
    root.style.setProperty(name, value);
  }
}
