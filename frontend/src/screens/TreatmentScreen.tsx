import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api } from '../api';
import type { PlanEntry, Reminder, ReminderStatus } from '../api/types';
import { Disclaimer } from '../components/Disclaimer';
import { strings } from '../strings';

/** UC-MED-01..03 (mock): the plan only repeats what the user entered; no dose advice. */
export function TreatmentScreen() {
  const plan = useQuery({ queryKey: ['plan'], queryFn: () => api.getTreatmentPlan() });
  const reminders = useQuery({ queryKey: ['reminders'], queryFn: () => api.getReminders() });
  const adherence = useQuery({ queryKey: ['adherence'], queryFn: () => api.getAdherence() });

  const [added, setAdded] = useState<PlanEntry[]>([]);
  const [statusById, setStatusById] = useState<Record<string, ReminderStatus>>({});
  const [medicine, setMedicine] = useState('');
  const [dose, setDose] = useState('');
  const [time, setTime] = useState('');
  const [error, setError] = useState<string | null>(null);

  const entries = [...(plan.data ?? []), ...added];
  const allReminders: Reminder[] = [
    ...(reminders.data ?? []),
    ...added.flatMap((e) =>
      e.times.map((t) => ({
        id: `${e.id}-${t}`,
        entryId: e.id,
        time: t,
        status: 'scheduled' as const,
      })),
    ),
  ].sort((a, b) => a.time.localeCompare(b.time));

  function onAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!medicine.trim() || !dose.trim() || !time) {
      setError(strings.entryMissing);
      return;
    }
    setError(null);
    setAdded((prev) => [
      ...prev,
      {
        id: `added-${prev.length + 1}`,
        medicine: medicine.trim(),
        doseAsEntered: dose.trim(),
        times: [time],
      },
    ]);
    setMedicine('');
    setDose('');
    setTime('');
  }

  const medicineName = (entryId: string) =>
    entries.find((e) => e.id === entryId)?.medicine ?? entryId;

  return (
    <>
      <title>{`${strings.treatmentHeading} — ${strings.appName}`}</title>
      <h1>{strings.treatmentHeading}</h1>
      <p className="note">{strings.treatmentNote}</p>
      <Disclaimer />

      <h2>{strings.planHeading}</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">{strings.colMedicine}</th>
              <th scope="col">{strings.colDose}</th>
              <th scope="col">{strings.colTimes}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <th scope="row">{e.medicine}</th>
                <td>
                  {e.doseAsEntered} <span className="muted">({strings.enteredByUser})</span>
                </td>
                <td>{e.times.join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="form" onSubmit={onAdd} noValidate>
        <label htmlFor="plan-medicine">{strings.medicineLabel}</label>
        <input
          id="plan-medicine"
          type="text"
          value={medicine}
          onChange={(e) => setMedicine(e.target.value)}
        />
        <label htmlFor="plan-dose">{strings.doseLabel}</label>
        <input id="plan-dose" type="text" value={dose} onChange={(e) => setDose(e.target.value)} />
        <label htmlFor="plan-time">{strings.timeLabel}</label>
        <input id="plan-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="button">
          {strings.addEntry}
        </button>
      </form>

      <h2>{strings.remindersHeading}</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">{strings.colTime}</th>
              <th scope="col">{strings.colMedicine}</th>
              <th scope="col">{strings.colStatus}</th>
              <th scope="col">{strings.colAction}</th>
            </tr>
          </thead>
          <tbody>
            {allReminders.map((r) => {
              const status = statusById[r.id] ?? r.status;
              const name = medicineName(r.entryId);
              const set = (s: ReminderStatus) => setStatusById((prev) => ({ ...prev, [r.id]: s }));
              const open = status === 'scheduled' || status === 'snoozed';
              return (
                <tr key={r.id}>
                  <td>{r.time}</td>
                  <th scope="row">{name}</th>
                  <td>{strings.reminderStatus[status]}</td>
                  <td>
                    {open && (
                      <span className="row-actions">
                        <button
                          type="button"
                          aria-label={`${strings.markTaken}: ${name} ${r.time}`}
                          onClick={() => set('taken')}
                        >
                          {strings.markTaken}
                        </button>
                        <button
                          type="button"
                          aria-label={`${strings.snooze}: ${name} ${r.time}`}
                          onClick={() => set('snoozed')}
                        >
                          {strings.snooze}
                        </button>
                        <button
                          type="button"
                          aria-label={`${strings.skip}: ${name} ${r.time}`}
                          onClick={() => set('skipped')}
                        >
                          {strings.skip}
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h2>{strings.adherenceHeading}</h2>
      {adherence.data ? (
        <p>{strings.adherenceSummary(adherence.data.taken, adherence.data.total)}</p>
      ) : (
        <p>{strings.loading}</p>
      )}
    </>
  );
}
