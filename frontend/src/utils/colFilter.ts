/**
 * Iter 346 (user request) — Excel-style per-column header filters for the
 * salary process grids. Supports plain substring match plus numeric
 * operators: ">100", "<5000", ">=26", "<=0", "=15000".
 */
export function matchColFilter(value: any, expr: string): boolean {
  const f = (expr || "").trim();
  if (!f) return true;
  const m = f.match(/^(>=|<=|=|>|<)\s*(-?\d+(?:\.\d+)?)$/);
  if (m) {
    const n = Number(value ?? 0);
    const t = Number(m[2]);
    switch (m[1]) {
      case ">": return n > t;
      case "<": return n < t;
      case ">=": return n >= t;
      case "<=": return n <= t;
      default: return Math.abs(n - t) < 0.005;
    }
  }
  return String(value ?? "").toLowerCase().includes(f.toLowerCase());
}

export function rowPassesColFilters(
  row: any,
  filters: Record<string, string>,
  getters: Record<string, (r: any) => any>,
): boolean {
  for (const [key, expr] of Object.entries(filters)) {
    if (!expr?.trim()) continue;
    const get = getters[key];
    if (!get) continue;
    if (!matchColFilter(get(row), expr)) return false;
  }
  return true;
}
