/**
 * FICTIONAL DATA. These are not real hospitals: names, addresses and distances are invented for
 * the demo. Real hospital records are curated separately (SDS Appendix C) and are never placed here.
 * No phone numbers are included on purpose.
 */
import type { Hospital } from '../api/types';

export const demoHospitals: Hospital[] = [
  {
    id: 'demo-a',
    name: 'Demo Hospital A',
    facilityType: 'oncology_center',
    address: '1 Example Road, Demo City (fictional)',
    distanceKm: 2.4,
  },
  {
    id: 'demo-b',
    name: 'Demo Hospital B',
    facilityType: 'general_hospital_oncology_ward',
    address: '2 Sample Street, Demo City (fictional)',
    distanceKm: 3.9,
  },
  {
    id: 'demo-c',
    name: 'Demo Hospital C',
    facilityType: 'ent_clinic',
    address: '3 Placeholder Avenue, Demo City (fictional)',
    distanceKm: 5.1,
  },
  {
    id: 'demo-d',
    name: 'Demo Hospital D',
    facilityType: 'oncology_center',
    address: '4 Fictional Lane, Demo Town (fictional)',
    distanceKm: 8.7,
  },
  {
    id: 'demo-e',
    name: 'Demo Hospital E',
    facilityType: 'ent_clinic',
    address: '5 Mock Boulevard, Demo Town (fictional)',
    distanceKm: 12.3,
  },
];
