/**
 * User-facing strings, kept in one place so they can be edited (or localized to Urdu) later.
 *
 * Medical wording rules (CLAUDE.md section 3, SRS Appendix B):
 * - `outcomeText` is copied VERBATIM from SRS Appendix B. Do not reword it.
 * - The non-diagnostic disclaimer appears on every result and on the chatbot screen (NFR-SAF-01).
 * - No text here may give a diagnosis, a dose, or advice to stop or change medication.
 */
import type { Outcome } from './domain/outcome';

export const strings = {
  appName: 'OSCC Health Intelligence',
  skipToContent: 'Skip to main content',
  demoBanner: 'Demo mode — sample data, not a medical device',
  primaryNavLabel: 'Main',
  flowLabel: 'Screening steps',
  footer:
    'Research prototype (FAST-NU Karachi final year project). Not a medical device. Every number in this demo is sample data unless it says "Results from run folders".',

  // Navigation and flow steps
  nav: {
    home: 'Home',
    upload: 'Upload',
    result: 'Result',
    hospitals: 'Hospitals',
    support: 'Support',
    compare: 'Compare models',
    treatment: 'Treatment & reminders',
    admin: 'Admin benchmark',
    login: 'Log in',
    register: 'Register',
  },
  signedInAs: (name: string) => `Signed in as ${name} (demo)`,
  logOut: 'Log out',

  // Disclaimer (NFR-SAF-01). Based on the SRS constraint "a research prototype and screening aid;
  // it is not a medical device and must not be used for clinical decisions".
  disclaimerHeading: 'Important',
  disclaimer:
    'This is a research prototype and screening aid. It is not a medical device and does not give a diagnosis. Do not use it to make clinical decisions; always consult a qualified doctor.',

  // Data sources (report JSON vs fixtures)
  sourceReport: 'Results from run folders',
  sourceSample: 'Sample data — not real results',
  reportGeneratedAt: (when: string) => `Report generated ${when} (PKT)`,
  loading: 'Loading…',

  // Home
  homeHeading: 'OSCC Health Intelligence',
  homeIntro:
    'This demo shows the planned screens of the system: screening of H&E oral histopathology images, comparison of models, nearest hospitals, treatment reminders and an administrator benchmark.',
  homeDemoNote:
    'No real model runs here. Results come from fixed sample cases so the screens can be reviewed before the real system is connected.',
  homeStart: 'Start the demo (log in)',
  homeSkipLogin: 'Go straight to upload',

  // Login / Register (UC-USR-01, UC-USR-02) — mock
  loginHeading: 'Log in',
  registerHeading: 'Register',
  authDemoNote:
    'Demo only: any input is accepted, nothing is sent anywhere and no password is stored.',
  emailLabel: 'Email',
  passwordLabel: 'Password',
  nameLabel: 'Full name',
  loginSubmit: 'Log in',
  registerSubmit: 'Create demo account',
  noAccount: 'No account yet?',
  haveAccount: 'Already registered?',
  demoUserName: 'Demo user',

  // Upload (UC-SCR-01)
  uploadHeading: 'Upload an H&E image',
  uploadIntro:
    'Choose an image file or one of the sample cases. In this demo the file never leaves your browser and no model is run.',
  uploadFileLabel: 'Histopathology image (JPEG, PNG or TIFF, up to 20 MB)',
  uploadSubmit: 'Screen this image (demo)',
  uploadNoFile: 'Choose a file first.',
  uploadBadType: 'This file type is not supported. Choose a JPEG, PNG or TIFF image.',
  uploadTooLarge: 'This file is larger than 20 MB. Choose a smaller image.',
  uploadFileRule:
    'Demo rule: the sample case is picked from the file name, so the same file name always gives the same sample result.',
  samplesHeading: 'Or choose a sample case',
  sampleChoose: (title: string) => `Use ${title}`,

  // Result (UC-SCR-02)
  resultHeading: 'Screening result',
  resultNotFound: 'This sample case does not exist.',
  resultFromSample: (title: string) =>
    `Demo: this is the fixed result of ${title}. No model was run on any image.`,
  resultFromFile: (fileName: string, title: string) =>
    `Demo: the file "${fileName}" was not analysed. ${title} was chosen from its file name.`,
  probabilityLabel: 'OSCC probability (p)',
  thresholdLabel: 'Threshold (τ)',
  marginLabel: 'Inconclusive margin (m)',
  modelVersionLabel: 'Model version',
  outcomeRuleLabel: 'Rule applied',
  explanationHeading: 'Explanation map',
  explanationPlaceholder:
    'Placeholder. When a real model is connected, a heat map (Grad-CAM for CNNs, attention rollout for ViT) will show which regions influenced the result.',
  findHospitalsPrompt: 'Find nearest hospitals',
  hospitalsLink: 'Hospital search',
  supportLink: 'Support',
  compareLink: 'Compare models for this case',
  newScreening: 'Screen another image',

  // Outcomes. `outcomeLabel` is a short label shown with the icon; `outcomeText` is SRS Appendix B verbatim.
  outcomeLabel: {
    oscc_suspected: 'OSCC suspected',
    inconclusive: 'Inconclusive',
    non_oscc: 'No OSCC features detected',
  } satisfies Record<Outcome, string>,
  outcomeText: {
    oscc_suspected: 'Features suggestive of OSCC detected — medical review recommended.',
    inconclusive: 'Inconclusive — medical review recommended.',
    non_oscc:
      'No OSCC features detected by the model — this is not a diagnosis; consult a doctor if symptoms persist.',
  } satisfies Record<Outcome, string>,
  outcomeRule: {
    oscc_suspected: 'p ≥ τ + m',
    inconclusive: 'τ − m ≤ p < τ + m',
    non_oscc: 'p < τ − m',
  } satisfies Record<Outcome, string>,

  // Compare (UC-SCR-03)
  compareHeading: 'Compare models',
  compareIntro:
    'CNN, Vision Transformer and tabular models side by side. Predictions for a sample case are always sample data; benchmark metrics come from the research report when it is available.',
  compareCaseLabel: 'Sample case',
  comparePredictionsHeading: 'Predictions for this sample case',
  compareMetricsHeading: 'Benchmark metrics (test set)',
  colModel: 'Model',
  colFamily: 'Family',
  colProbability: 'Probability (p)',
  colThreshold: 'τ',
  colOutcome: 'Outcome',
  colStatus: 'Status',
  colAuc: 'AUC (95% CI)',
  colRecall: 'Recall (95% CI)',
  colSpecificity: 'Specificity (95% CI)',
  colF1: 'F1 (95% CI)',
  colParams: 'Parameters',
  colLatency: 'CPU latency (ms)',
  colActive: 'Active',
  notYetRun: 'not yet run',
  notApplicable: 'n/a',
  tabularNote:
    'Tabular models use a different input (a table of features, not an image), so they have no prediction for an image case.',

  // Hospitals (UC-HOS-01..03) — fictional
  hospitalsHeading: 'Nearest hospitals',
  hospitalsDemoNote:
    'Demo: all hospitals, addresses and distances below are fictional. No location is read from your device.',
  hospitalsLocation: 'Location used: demo location (fictional)',
  facilityFilterLegend: 'Facility type',
  facilityType: {
    oncology_center: 'Oncology centre',
    ent_clinic: 'ENT clinic',
    general_hospital_oncology_ward: 'General hospital (oncology ward)',
  },
  distanceLabel: (km: string) => `${km} km (straight-line distance)`,
  straightLineNote:
    'Distances are straight-line distances, not road distances. A road route is not available in the demo.',
  hospitalDetails: 'Details',
  hospitalAddress: 'Address',
  hospitalPhone: 'Phone',
  phoneNotInDemo: 'Not shown in the demo',
  noHospitals: 'No hospitals match the selected facility types.',
  continueToSupport: 'Continue to support',

  // Treatment plan and reminders (UC-MED-01..03)
  treatmentHeading: 'Treatment plan and medication reminders',
  treatmentNote:
    'Reminders only repeat what you entered from your prescription. This app never suggests a dose and never advises starting, stopping or changing a medicine — ask your doctor or pharmacist.',
  planHeading: 'Your plan (as entered)',
  medicineLabel: 'Medicine name',
  doseLabel: 'Dose as written on your prescription',
  timeLabel: 'Reminder time',
  addEntry: 'Add to plan',
  entryMissing: 'Enter the medicine name, the dose from your prescription and a time.',
  enteredByUser: 'entered by the user',
  remindersHeading: 'Today’s reminders',
  reminderStatus: {
    scheduled: 'Scheduled',
    taken: 'Taken',
    skipped: 'Skipped',
    snoozed: 'Snoozed',
    missed: 'Missed',
  },
  markTaken: 'Mark as taken',
  snooze: 'Snooze 10 min',
  skip: 'Skip',
  adherenceHeading: 'Adherence (last 7 days)',
  adherenceSummary: (taken: number, total: number) =>
    `${taken} of ${total} reminders marked as taken`,
  colMedicine: 'Medicine',
  colDose: 'Dose (as entered)',
  colTimes: 'Times',
  colTime: 'Time',
  colAction: 'Action',

  // Admin (UC-ADM-03)
  adminHeading: 'Admin benchmark and model registry',
  adminNote:
    'Demo: in the real system only administrators see this page. Registry statuses here are sample data.',
  registryHeading: 'Model registry',
  activeYes: 'Active',
  activeNo: '—',
  notActive: 'Not active',
  registryStatus: {
    registered: 'Registered',
    validated: 'Validated',
    active: 'Active',
    retired: 'Retired',
  },
  dummyModelNote:
    'dummy-v0 is the demo model the screens are built against; it has no real weights and no metrics.',
  reportNotes: 'Report notes',

  // Support / chatbot placeholder (UC-CHT-01)
  supportHeading: 'Support',
  chatbotHeading: 'Patient-support chatbot — coming soon',
  chatbotBody:
    'The chatbot is not available yet (work on it is on hold). There is no message box, so nothing can be sent.',
  chatbotHelp:
    'If you are worried about a symptom or a result, please speak to a doctor or visit a hospital.',
  treatmentLink: 'Treatment plan and reminders',

  // Not found
  notFoundHeading: 'Page not found',
  notFoundBody: 'The page you asked for does not exist.',
  backHome: 'Go to the home page',
} as const;
