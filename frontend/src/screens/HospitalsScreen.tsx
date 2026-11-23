import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { FacilityType } from '../api/types';
import { paths } from '../navigation';
import { strings } from '../strings';

const FACILITY_TYPES = Object.keys(strings.facilityType) as FacilityType[];

/** UC-HOS-01..03 (mock): fictional hospitals, straight-line distances, filter by facility type. */
export function HospitalsScreen() {
  const hospitals = useQuery({ queryKey: ['hospitals'], queryFn: () => api.getHospitals() });
  const [selected, setSelected] = useState<Set<FacilityType>>(new Set(FACILITY_TYPES));

  function toggle(type: FacilityType) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  const visible = (hospitals.data ?? []).filter((h) => selected.has(h.facilityType));

  return (
    <>
      <title>{`${strings.hospitalsHeading} — ${strings.appName}`}</title>
      <h1>{strings.hospitalsHeading}</h1>
      <p className="note">{strings.hospitalsDemoNote}</p>
      <p>{strings.hospitalsLocation}</p>

      <fieldset className="filters">
        <legend>{strings.facilityFilterLegend}</legend>
        {FACILITY_TYPES.map((type) => (
          <label key={type} className="checkbox">
            <input type="checkbox" checked={selected.has(type)} onChange={() => toggle(type)} />
            {strings.facilityType[type]}
          </label>
        ))}
      </fieldset>

      <p className="note">{strings.straightLineNote}</p>

      {hospitals.isPending ? (
        <p>{strings.loading}</p>
      ) : visible.length === 0 ? (
        <p role="status">{strings.noHospitals}</p>
      ) : (
        <ul className="card-list" aria-label={strings.hospitalsHeading}>
          {visible.map((h) => (
            <li key={h.id} className="card">
              <h2>{h.name}</h2>
              <p>{strings.facilityType[h.facilityType]}</p>
              <p>{strings.distanceLabel(h.distanceKm.toFixed(1))}</p>
              <details>
                <summary>{strings.hospitalDetails}</summary>
                <dl className="facts">
                  <div>
                    <dt>{strings.hospitalAddress}</dt>
                    <dd>{h.address}</dd>
                  </div>
                  <div>
                    <dt>{strings.hospitalPhone}</dt>
                    <dd>{strings.phoneNotInDemo}</dd>
                  </div>
                </dl>
              </details>
            </li>
          ))}
        </ul>
      )}

      <p className="actions">
        <Link className="button" to={paths.support}>
          {strings.continueToSupport}
        </Link>
      </p>
    </>
  );
}
