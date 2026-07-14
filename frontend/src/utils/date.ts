/**
 * Centralised date/time formatting for the whole app.
 *
 * The app follows Indian conventions: DD-MM-YYYY for dates,
 * DD-MM-YYYY HH:MM for date+time, HH:MM (24h) for pure times.
 * All helpers accept null/undefined/empty and return "-" for
 * safe rendering inside <Text> without crashing.
 *
 * Iter 77 - Standardised on DASH separator app-wide (was mixed slash /
 * dash before). Any legacy DD/MM/YYYY user input is still accepted by
 * the parsers.
 */

const DASH = "\u2014"; // - em dash used as empty placeholder

function toDate(input: string | number | Date | null | undefined): Date | null {
  if (input === null || input === undefined || input === "") return null;
  const d = input instanceof Date ? input : new Date(input);
  return Number.isNaN(d.getTime()) ? null : d;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/**
 * Format a date as DD-MM-YYYY. Accepts:
 *  - ISO strings ("2026-06-14T09:12:33Z")
 *  - Plain YYYY-MM-DD strings ("2026-06-14")
 *  - Date objects
 *  - Timestamps (ms since epoch)
 * Returns em-dash placeholder when the input can't be parsed.
 */
export function formatDate(
  input: string | number | Date | null | undefined,
  fallback: string = DASH,
): string {
  const d = toDate(input);
  if (!d) return fallback;
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`;
}

/**
 * Format as DD-MM-YYYY HH:MM (24h). Uses local device timezone.
 */
export function formatDateTime(
  input: string | number | Date | null | undefined,
  fallback: string = DASH,
): string {
  const d = toDate(input);
  if (!d) return fallback;
  return (
    `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/**
 * Format only the time portion as HH:MM (24h).
 */
export function formatTime(
  input: string | number | Date | null | undefined,
  fallback: string = DASH,
): string {
  const d = toDate(input);
  if (!d) return fallback;
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Parse a DD-MM-YYYY (or legacy DD/MM/YYYY) string into a Date.
 * Returns null on invalid input. Useful for form inputs.
 */
export function parseDDMMYYYY(v: string | null | undefined): Date | null {
  if (!v) return null;
  const m = String(v).trim().match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
  if (!m) return null;
  const [, dd, mm, yyyy] = m;
  const d = new Date(Number(yyyy), Number(mm) - 1, Number(dd));
  if (
    d.getFullYear() !== Number(yyyy) ||
    d.getMonth() !== Number(mm) - 1 ||
    d.getDate() !== Number(dd)
  ) {
    return null;
  }
  return d;
}

/**
 * Convert a DD-MM-YYYY (or legacy DD/MM/YYYY) string into the ISO date
 * form (YYYY-MM-DD) the backend expects. Returns null if it can't parse.
 */
export function ddmmyyyyToISO(v: string | null | undefined): string | null {
  const d = parseDDMMYYYY(v);
  if (!d) return null;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Convert an ISO YYYY-MM-DD (or any Date-parseable input) into DD-MM-YYYY
 * suitable for prefilling a form input.
 */
export function isoToDDMMYYYY(v: string | null | undefined): string {
  return formatDate(v, "");
}

/**
 * Legacy alias kept for backwards compatibility with older screens that
 * imported ``formatDateDash`` specifically for the dashed variant. Now
 * that ``formatDate`` returns dashes by default, this just forwards.
 */
export function formatDateDash(
  input: string | number | Date | null | undefined,
  fallback: string = DASH,
): string {
  return formatDate(input, fallback);
}

/** Legacy alias - forwards to :func:`isoToDDMMYYYY`. */
export function isoToDDMMYYYYDash(v: string | null | undefined): string {
  return isoToDDMMYYYY(v);
}

/** Legacy alias - forwards to :func:`parseDDMMYYYY`. */
export function parseDDMMYYYYDash(v: string | null | undefined): Date | null {
  return parseDDMMYYYY(v);
}

/** Legacy alias - forwards to :func:`ddmmyyyyToISO`. */
export function ddmmyyyyDashToISO(v: string | null | undefined): string | null {
  return ddmmyyyyToISO(v);
}

/**
 * Format a payslip month string like "2026-06" as "Jun 2026".
 */
export function formatMonth(
  input: string | null | undefined,
  fallback: string = DASH,
): string {
  if (!input) return fallback;
  const m = String(input).match(/^(\d{4})-(\d{2})/);
  if (!m) return input;
  const year = Number(m[1]);
  const month = Number(m[2]) - 1;
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${months[month] ?? m[2]} ${year}`;
}
