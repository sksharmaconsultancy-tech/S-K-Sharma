"""ZKTeco .dat biometric-punch parser (Iter 77).

The ZKTeco terminals export two flat text files with tab-separated columns:

    <bio_code>  <YYYY-MM-DD HH:MM:SS>  <status>  <verify_type>  <workcode>  <reserved>

* ``IN.dat``  contains punches for entry
* ``OUT.dat`` contains punches for exit

Both files can also be combined into a single upload where the ``kind`` is
inferred from the status column (0=IN, 1=OUT) - we handle both shapes.

Public entry-points:

* :func:`parse_zk_dat_lines` - tolerant line-level parser.
* :func:`import_zk_dat_bytes` - end-to-end: parses + inserts + dedupes into
  ``db.attendance``. Returns a stats dict for the UI.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Line parsing
# ---------------------------------------------------------------------------

def parse_zk_dat_lines(
    text: str,
    default_kind: Optional[str] = None,
) -> List[Tuple[str, datetime, Optional[str]]]:
    """Parse one .dat file's content. Returns list of
    ``(bio_code, datetime, kind_hint)`` tuples. ``kind_hint`` is either
    ``"in"``, ``"out"`` or ``None`` (when unknown - the caller supplies
    ``default_kind`` for the whole file).

    Skips malformed lines silently; the caller can measure ``bad`` via the
    difference between input lines and output rows.
    """
    rows: List[Tuple[str, datetime, Optional[str]]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = re.split(r"\s+", line, maxsplit=6)
        if len(parts) < 3:
            continue
        bio = parts[0].strip()
        ts_raw = f"{parts[1]} {parts[2]}"
        try:
            dt = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue
        # Optional inline kind from the 4th column when present.
        # ZKTeco status codes: 0=CheckIn, 1=CheckOut, 4=Overtime In, 5=Overtime Out
        kind: Optional[str] = default_kind
        if len(parts) >= 4 and parts[3].strip().isdigit():
            status = int(parts[3])
            if status in (0, 4):
                kind = "in"
            elif status in (1, 5):
                kind = "out"
        rows.append((bio, dt, kind))
    return rows


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Iter 106 — Excel (.xlsx / .xls) punch imports. The employer keeps IN
# punches in one sheet/file and OUT punches in another. Expected columns
# (header row optional): CODE | DATE | TIME  — or CODE | DATETIME.
# We normalise every row into the same .dat text shape so the proven
# import pipeline (mapping, dedupe, range filter) is reused 1:1.
# ---------------------------------------------------------------------------

def _cell_to_dt(date_v: Any, time_v: Any = None) -> Optional[datetime]:
    """Combine a date cell + optional time cell into a datetime."""
    from datetime import date as _date, time as _time, timedelta as _td
    d: Optional[datetime] = None
    if isinstance(date_v, datetime):
        d = date_v
    elif isinstance(date_v, _date):
        d = datetime(date_v.year, date_v.month, date_v.day)
    elif isinstance(date_v, (int, float)) and date_v > 20000:
        # Excel serial date (xlrd already converts when told; safeguard)
        d = datetime(1899, 12, 30) + _td(days=float(date_v))
    elif isinstance(date_v, str):
        s = date_v.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S",
                    "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M",
                    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
            try:
                d = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if d is None:
        return None
    # Merge the separate time cell when the date cell had no time part.
    if time_v is not None and d.hour == 0 and d.minute == 0 and d.second == 0:
        if isinstance(time_v, datetime):
            d = d.replace(hour=time_v.hour, minute=time_v.minute, second=time_v.second)
        elif isinstance(time_v, _time):
            d = d.replace(hour=time_v.hour, minute=time_v.minute, second=time_v.second)
        elif isinstance(time_v, (int, float)) and 0 <= float(time_v) < 1:
            secs = round(float(time_v) * 86400)
            d = d.replace(hour=secs // 3600, minute=(secs % 3600) // 60, second=secs % 60)
        elif isinstance(time_v, str) and time_v.strip():
            t = time_v.strip()
            for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
                try:
                    tt = datetime.strptime(t, fmt)
                    d = d.replace(hour=tt.hour, minute=tt.minute, second=tt.second)
                    break
                except ValueError:
                    continue
    return d.replace(tzinfo=timezone.utc)


def excel_punches_to_dat_text(data: bytes, filename: str = "") -> str:
    """Convert an Excel sheet of punches into ZK .dat text lines
    (``code<TAB>YYYY-MM-DD HH:MM:SS``). Raises ValueError on unreadable
    files."""
    rows: List[Tuple[Any, Any, Any]] = []
    name = (filename or "").lower()
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sh = book.sheet_by_index(0)
        for r in range(sh.nrows):
            vals = sh.row_values(r)
            c0 = vals[0] if len(vals) > 0 else None
            c1 = vals[1] if len(vals) > 1 else None
            c2 = vals[2] if len(vals) > 2 else None
            # xlrd returns dates as floats — convert via xldate when possible
            if isinstance(c1, float) and c1 > 1:
                try:
                    c1 = datetime(*xlrd.xldate_as_tuple(c1, book.datemode))
                except Exception:
                    pass
            if isinstance(c2, float) and 0 <= c2 < 1:
                pass  # handled as fraction-of-day in _cell_to_dt
            rows.append((c0, c1, c2))
    else:
        import io
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        for vals in ws.iter_rows(values_only=True):
            c0 = vals[0] if len(vals) > 0 else None
            c1 = vals[1] if len(vals) > 1 else None
            c2 = vals[2] if len(vals) > 2 else None
            rows.append((c0, c1, c2))
        wb.close()

    lines: List[str] = []
    for c0, c1, c2 in rows:
        if c0 is None or c1 is None:
            continue
        code = str(c0).strip()
        if code.endswith(".0"):
            code = code[:-2]
        if not code or not any(ch.isdigit() for ch in code):
            continue  # header / junk row
        dt = _cell_to_dt(c1, c2)
        if dt is None:
            continue
        lines.append(f"{code}\t{dt:%Y-%m-%d} {dt:%H:%M:%S}")
    if not lines:
        raise ValueError(
            "No punch rows found — expected columns: CODE | DATE | TIME "
            "(or CODE | DATETIME).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Import driver
# ---------------------------------------------------------------------------

async def _build_bio_index(db, company_id: str) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    async for u in db.users.find(
        {
            "company_id": company_id,
            "role": "employee",
            "bio_code": {"$exists": True, "$ne": None},
        },
        {
            "_id": 0, "user_id": 1, "name": 1,
            "employee_code": 1, "bio_code": 1,
        },
    ):
        key = str(u["bio_code"]).lstrip("0") or "0"
        # First-writer wins so re-imports stay deterministic.
        index.setdefault(key, u)
    return index


async def import_zk_dat_bytes(
    db,
    *,
    company_id: str,
    in_bytes: Optional[bytes] = None,
    out_bytes: Optional[bytes] = None,
    combined_bytes: Optional[bytes] = None,
    from_date: Optional[str] = None,   # YYYY-MM-DD (inclusive) - optional filter
    to_date: Optional[str] = None,     # YYYY-MM-DD (inclusive) - optional filter
    source_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse + insert ZKTeco punches into ``db.attendance``. Idempotent:
    re-running with the same file is a no-op (dedupes by user + at + kind
    + source)."""
    tag = source_tag or f"import:zk_upload_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    bio_index = await _build_bio_index(db, company_id)

    rows: List[Tuple[str, datetime, Optional[str]]] = []
    if in_bytes:
        rows.extend(parse_zk_dat_lines(in_bytes.decode("utf-8", errors="replace"),
                                       default_kind="in"))
    if out_bytes:
        rows.extend(parse_zk_dat_lines(out_bytes.decode("utf-8", errors="replace"),
                                       default_kind="out"))
    if combined_bytes:
        rows.extend(parse_zk_dat_lines(combined_bytes.decode("utf-8", errors="replace")))

    stats = {
        "total_lines": len(rows),
        "inserted": 0,
        "duplicate": 0,
        "unmapped": 0,
        "out_of_range": 0,
        "missing_kind": 0,
    }
    unmapped_seen: set = set()
    # Iter 86 - Buffer punches by (user_id, date) so we can re-classify
    # kind by punch-position when the source file gave every row the
    # same status byte (very common in ZKTeco combined exports).
    pending_by_user_day: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    for bio, dt, kind in rows:
        if kind is None:
            stats["missing_kind"] += 1
            continue
        date_str = dt.strftime("%Y-%m-%d")
        if from_date and date_str < from_date:
            stats["out_of_range"] += 1
            continue
        if to_date and date_str > to_date:
            stats["out_of_range"] += 1
            continue
        key = bio.lstrip("0") or "0"
        user = bio_index.get(key)
        if not user:
            stats["unmapped"] += 1
            unmapped_seen.add(bio)
            continue
        # Iter 86 - Re-classify kind by punch-position within the day.
        #
        # Real ZKTeco terminals often export EVERY punch with the same
        # `status` byte (e.g. always 1=CheckOut) because operators don't
        # configure the terminal function keys. Trusting that column
        # would classify every punch as "out" and the attendance grid
        # would then flag every day as `missing_punch` and show 0 hours.
        #
        # Fix: buffer by (user, date), sort by timestamp, then alternate
        # kinds - 1st=in, 2nd=out, 3rd=in (OT start), 4th=out (OT end).
        # This matches how the rest of the pipeline (`_pair_punches`,
        # `split_regular_ot_times`, `compute_textile_day`) already
        # expects the data to look.  Users who rely on genuine IN.dat +
        # OUT.dat uploads still get honored kinds because those come in
        # via `in_bytes` / `out_bytes` (default_kind="in"/"out") - the
        # position-reclassify only alters the FINAL kind when the file's
        # kinds all agree for a given (user, date) grouping.
        pending_by_user_day.setdefault(
            (user["user_id"], date_str), []
        ).append({
            "bio": bio,
            "user": user,
            "dt": dt,
            "raw_kind": kind,
        })
    # Now flush pending groups with position-inferred kind when needed.
    for (uid, date_str), items in pending_by_user_day.items():
        items.sort(key=lambda x: x["dt"])
        # If ALL rows on this (user, date) have identical raw_kind AND
        # there are 2+ punches, force alternating kind. This handles the
        # common ZKTeco `combined_file` case where every punch was
        # exported with the same status byte.
        #
        # We DO NOT alternate when there's only one punch on a day
        # because that would misclassify a user who legitimately
        # uploaded only IN.dat (or only OUT.dat) - each of those files
        # typically has exactly one punch per user per day. In such
        # cases we honor the explicit default_kind picked from the
        # filename slot.
        raw_kinds = {i["raw_kind"] for i in items}
        force_alternate = len(items) >= 2 and len(raw_kinds) <= 1
        for pos, item in enumerate(items):
            if force_alternate:
                kind = "in" if pos % 2 == 0 else "out"
            else:
                kind = item["raw_kind"]
            dt = item["dt"]
            user = item["user"]
            # Idempotency: skip if ANY punch already exists for this
            # user at the exact same timestamp+kind — regardless of the
            # import batch tag. (Previously the query included the
            # per-upload ``source`` tag which is timestamped, so
            # re-uploading the same .dat file silently duplicated every
            # punch and broke IN/OUT pairing in the attendance grid.)
            existing = await db.attendance.find_one(
                {
                    "user_id": user["user_id"],
                    "at": dt.isoformat(),
                    "kind": kind,
                },
                {"_id": 0, "record_id": 1},
            )
            if existing:
                stats["duplicate"] += 1
                continue
            record = {
                "record_id": f"imp_{uuid.uuid4().hex[:12]}",
                "user_id": user["user_id"],
                "company_id": company_id,
                "branch_id": None,
                "branch_name": "Biometric Terminal (imported)",
                "date": date_str,
                "kind": kind,
                "at": dt.isoformat(),
                "original_at": dt.isoformat(),
                "latitude": None,
                "longitude": None,
                "distance_m": None,
                "source": tag,
                "outside_geofence": False,
                "status": "approved",
                "decision_by": "system:import",
                "decision_at": now_iso(),
                "decision_reason": f"Uploaded ZKTeco .dat ({tag})",
                "device_serial": tag,
                "device_id": None,
                "device_verify_type": None,
                "selfie_base64": None,
                "created_at": now_iso(),
            }
            await db.attendance.insert_one(record)
            stats["inserted"] += 1

    stats["unmapped_bio_codes"] = sorted(
        unmapped_seen, key=lambda x: int(x) if x.isdigit() else 0,
    )[:50]
    stats["source_tag"] = tag
    return stats
