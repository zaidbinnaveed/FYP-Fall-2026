/**
 * Route and navigation config. Change paths, menu order or flow steps here; screens are wired to
 * these paths in `App.tsx`.
 */
import { strings } from './strings';

export const paths = {
  home: '/',
  login: '/login',
  register: '/register',
  upload: '/upload',
  result: '/result/:caseId',
  compare: '/compare',
  hospitals: '/hospitals',
  support: '/support',
  treatment: '/treatment',
  admin: '/admin',
} as const;

export function resultPath(caseId: string): string {
  return `/result/${encodeURIComponent(caseId)}`;
}

export function comparePath(caseId?: string): string {
  return caseId ? `/compare?case=${encodeURIComponent(caseId)}` : paths.compare;
}

export interface NavItem {
  path: string;
  label: string;
}

/** Main menu, in order. */
export const navItems: readonly NavItem[] = [
  { path: paths.upload, label: strings.nav.upload },
  { path: paths.compare, label: strings.nav.compare },
  { path: paths.hospitals, label: strings.nav.hospitals },
  { path: paths.treatment, label: strings.nav.treatment },
  { path: paths.support, label: strings.nav.support },
  { path: paths.admin, label: strings.nav.admin },
];

/** Guided flow Upload → Result → Hospitals → Support (SDS user-interface design). */
export const flowSteps: readonly {
  key: string;
  label: string;
  match: (path: string) => boolean;
}[] = [
  { key: 'upload', label: strings.nav.upload, match: (p) => p === paths.upload },
  { key: 'result', label: strings.nav.result, match: (p) => p.startsWith('/result/') },
  { key: 'hospitals', label: strings.nav.hospitals, match: (p) => p === paths.hospitals },
  { key: 'support', label: strings.nav.support, match: (p) => p === paths.support },
];
