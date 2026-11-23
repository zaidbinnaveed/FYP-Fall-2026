/**
 * EXAMPLE DATA. A treatment plan as a user might have entered it from a prescription.
 * The app never generates dose text; `doseAsEntered` stands for what the user typed.
 */
import type { Adherence, PlanEntry, Reminder } from '../api/types';

export const examplePlan: PlanEntry[] = [
  {
    id: 'entry-1',
    medicine: 'Example medicine A',
    doseAsEntered: 'As written on my prescription',
    times: ['08:00', '20:00'],
  },
  {
    id: 'entry-2',
    medicine: 'Example mouthwash B',
    doseAsEntered: 'As written on my prescription',
    times: ['13:00'],
  },
];

export const exampleReminders: Reminder[] = [
  { id: 'rem-1', entryId: 'entry-1', time: '08:00', status: 'taken' },
  { id: 'rem-2', entryId: 'entry-2', time: '13:00', status: 'scheduled' },
  { id: 'rem-3', entryId: 'entry-1', time: '20:00', status: 'scheduled' },
];

export const exampleAdherence: Adherence = { taken: 17, total: 21 };
