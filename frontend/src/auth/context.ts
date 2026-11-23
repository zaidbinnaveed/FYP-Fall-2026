import { createContext, useContext } from 'react';
import type { DemoUser } from '../api/types';

export interface DemoAuth {
  user: DemoUser | null;
  signIn(user: DemoUser): void;
  signOut(): void;
}

export const DemoAuthContext = createContext<DemoAuth>({
  user: null,
  signIn: () => undefined,
  signOut: () => undefined,
});

export function useDemoAuth(): DemoAuth {
  return useContext(DemoAuthContext);
}
