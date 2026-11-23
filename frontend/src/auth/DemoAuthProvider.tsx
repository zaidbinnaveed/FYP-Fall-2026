import { useMemo, useState, type ReactNode } from 'react';
import type { DemoUser } from '../api/types';
import { DemoAuthContext, type DemoAuth } from './context';

/** Mock sign-in kept in memory only (no token, no password, no storage). */
export function DemoAuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<DemoUser | null>(null);
  const value = useMemo<DemoAuth>(
    () => ({ user, signIn: setUser, signOut: () => setUser(null) }),
    [user],
  );
  return <DemoAuthContext.Provider value={value}>{children}</DemoAuthContext.Provider>;
}
