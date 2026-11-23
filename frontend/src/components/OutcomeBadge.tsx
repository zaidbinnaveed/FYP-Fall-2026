import type { Outcome } from '../domain/outcome';
import { strings } from '../strings';

/** Decorative icon; the meaning is always carried by the visible text label next to it. */
export function OutcomeIcon({ outcome }: { outcome: Outcome }) {
  const common = {
    width: 24,
    height: 24,
    viewBox: '0 0 24 24',
    'aria-hidden': true,
    focusable: false,
    className: 'outcome-icon',
    'data-icon': outcome,
  } as const;
  switch (outcome) {
    case 'oscc_suspected':
      // Warning triangle with exclamation mark
      return (
        <svg {...common}>
          <path d="M12 2 1 21h22L12 2z" fill="currentColor" />
          <rect x="11" y="8" width="2" height="7" fill="#fff" />
          <rect x="11" y="17" width="2" height="2" fill="#fff" />
        </svg>
      );
    case 'inconclusive':
      // Circle with question mark
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="11" fill="currentColor" />
          <path
            d="M9 9a3 3 0 1 1 4.2 2.7c-.8.4-1.2 1-1.2 1.8V14"
            stroke="#fff"
            strokeWidth="2"
            fill="none"
            strokeLinecap="round"
          />
          <rect x="11" y="16" width="2" height="2" fill="#fff" />
        </svg>
      );
    case 'non_oscc':
      // Circle with check mark
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="11" fill="currentColor" />
          <path
            d="m7 12.5 3.2 3.2L17 9"
            stroke="#fff"
            strokeWidth="2.2"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
  }
}

/** Outcome shown as icon + text label (never colour alone). */
export function OutcomeBadge({ outcome, large = false }: { outcome: Outcome; large?: boolean }) {
  return (
    <span className={`outcome outcome--${outcome}${large ? ' outcome--large' : ''}`}>
      <OutcomeIcon outcome={outcome} />
      <span className="outcome-label">{strings.outcomeLabel[outcome]}</span>
    </span>
  );
}
