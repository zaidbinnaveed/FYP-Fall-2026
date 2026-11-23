/** The API used by every screen. Swap `mockApi` for a real client here. */
import { mockApi } from './mock';
import type { Api } from './types';

export const api: Api = mockApi;
export type * from './types';
