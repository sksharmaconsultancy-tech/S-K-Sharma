/**
 * Iter 85 — Employee-type ordering.
 *
 * Business rule from S.K. Sharma & Co.: employee-type chips must appear
 * in a specific sequence regardless of the DB order:
 *     1. Staff  →  2. Labour  →  3. Other  →  4. Helping Staff
 *
 * Any additional type names discovered in the data are appended after
 * these four in alphabetical order so nothing goes missing.
 *
 * Additionally (Iter 85 pt 2): Salary Process screens should NOT show
 * types with zero active employees. Callers can opt-in to this filter
 * via ``sortEmployeeTypes(list, { activeOnly: true })``.
 */

const CANONICAL_ORDER = ["Staff", "Labour", "Other", "Helping Staff"];

function norm(s?: string | null): string {
  return (s || "").trim().toLowerCase();
}

function canonicalIndex(name: string): number {
  const n = norm(name);
  return CANONICAL_ORDER.findIndex((c) => norm(c) === n);
}

export type EmpTypeItem = { name: string; count?: number };

/**
 * Sorts a list of employee-type items into the canonical business
 * sequence. When ``activeOnly`` is true, items whose count is 0 or
 * missing name are dropped (Salary Process semantics).
 */
export function sortEmployeeTypes<T extends EmpTypeItem>(
  items: T[],
  opts?: { activeOnly?: boolean },
): T[] {
  let list = [...items];
  if (opts?.activeOnly) {
    list = list.filter((t) => (t.count ?? 0) > 0 && (t.name || "").trim() !== "");
  }
  return list.sort((a, b) => {
    const ai = canonicalIndex(a.name);
    const bi = canonicalIndex(b.name);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return (a.name || "").localeCompare(b.name || "");
  });
}
