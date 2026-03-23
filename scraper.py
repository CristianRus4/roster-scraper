import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import certifi
from zoneinfo import ZoneInfo

API_BASE_URL = "https://loadedhub.com/api"
DEFAULT_EMPLOYEE_NAME = "Cristian Rus"
DEFAULT_WEEKS_AHEAD = 4
DEFAULT_PUBLIC_ROSTER_URL = (
    "https://loadedhub.com/App/PublicRoster#/roster/"
    "03138d50-b542-4ca2-952f-8756ef67c2ba/"
    "e023f92d-acb6-91a7-fbc0-2555e704bf53"
)
OUTPUT_PATH = Path("roster.ics")
SUMMARY_PATH = Path("roster_summary.txt")
PUBLIC_DIR = Path("public")
PUBLIC_OUTPUT_PATH = PUBLIC_DIR / "roster.ics"
PUBLIC_INDEX_PATH = PUBLIC_DIR / "index.html"
PUBLIC_NOJEKYLL_PATH = PUBLIC_DIR / ".nojekyll"
LOCATION = "1 Taranaki Street, Te Aro, Wellington, 6011"
COWORKER_ALLOWED_ROLES = frozenset({"admin", "foh", "manager"})
CALENDAR_NAME = "Cristian Rus Roster"
PRODID = "-//roster-scraper//Cristian Rus Roster//EN"


class ScraperError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicRosterConfig:
    company_id: str
    token: str


@dataclass(frozen=True)
class ShiftEvent:
    shift_id: str
    staff_member_id: str
    staff_name: str
    role_name: str
    jobs: tuple[str, ...]
    breaks_display: tuple[str, ...]
    start: dt.datetime
    end: dt.datetime


@dataclass(frozen=True)
class Preferences:
    week_start: int
    day_start: dt.time
    timezone: str
    company_name: str


def load_settings() -> tuple[str, str, int]:
    public_roster_url = os.environ.get("PUBLIC_ROSTER_URL", "").strip() or DEFAULT_PUBLIC_ROSTER_URL
    employee_name = os.environ.get("ROSTER_EMPLOYEE_NAME", DEFAULT_EMPLOYEE_NAME).strip() or DEFAULT_EMPLOYEE_NAME
    weeks_ahead_raw = os.environ.get("ROSTER_WEEKS_AHEAD", str(DEFAULT_WEEKS_AHEAD)).strip()

    try:
        weeks_ahead = int(weeks_ahead_raw)
    except ValueError as exc:
        raise ScraperError(f"ROSTER_WEEKS_AHEAD must be an integer, got {weeks_ahead_raw!r}") from exc

    if weeks_ahead < 0:
        raise ScraperError("ROSTER_WEEKS_AHEAD must be zero or greater")

    return public_roster_url, employee_name, weeks_ahead


def parse_public_roster_url(public_roster_url: str) -> PublicRosterConfig:
    fragment = urlparse(public_roster_url).fragment
    match = re.fullmatch(r"/roster/([^/]+)/([^/?#]+)", fragment)
    if not match:
        raise ScraperError(
            "PUBLIC_ROSTER_URL must look like "
            "https://loadedhub.com/App/PublicRoster#/roster/<companyId>/<token>"
        )
    return PublicRosterConfig(company_id=match.group(1), token=match.group(2))


def http_get_json(path: str, params: dict[str, Any], retries: int = 3, timeout: int = 30) -> dict[str, Any]:
    url = f"{API_BASE_URL}{path}?{urlencode(params)}"
    last_error: Exception | None = None

    ssl_context = ssl.create_default_context(cafile=certifi.where())

    for attempt in range(1, retries + 1):
        request = Request(url, headers={"User-Agent": "roster-scraper/2.0", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout, context=ssl_context) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(2 ** (attempt - 1))

    raise ScraperError(f"Request failed for {path}: {last_error}") from last_error


def fetch_preferences(config: PublicRosterConfig) -> Preferences:
    payload = http_get_json(
        "/time-roster-public/preferences",
        {"companyId": config.company_id, "token": config.token},
    )

    required_keys = {"weekStart", "dayStart", "localeTimeZone", "companyName"}
    missing = required_keys.difference(payload)
    if missing:
        raise ScraperError(f"Preferences payload missing keys: {sorted(missing)}")

    try:
        day_start = dt.time.fromisoformat(payload["dayStart"])
    except ValueError as exc:
        raise ScraperError(f"Invalid dayStart value: {payload['dayStart']!r}") from exc

    return Preferences(
        week_start=int(payload["weekStart"]),
        day_start=day_start,
        timezone=payload["localeTimeZone"],
        company_name=payload["companyName"],
    )


def api_weekday_to_python(week_start: int) -> int:
    if week_start < 0 or week_start > 6:
        raise ScraperError(f"Unsupported weekStart value: {week_start}")
    return (week_start - 1) % 7


def calculate_window(preferences: Preferences, now: dt.datetime | None = None, weeks_ahead: int = DEFAULT_WEEKS_AHEAD) -> tuple[dt.datetime, dt.datetime]:
    tz = ZoneInfo(preferences.timezone)
    current = now.astimezone(tz) if now else dt.datetime.now(tz)
    current_day_start = current.replace(
        hour=preferences.day_start.hour,
        minute=preferences.day_start.minute,
        second=preferences.day_start.second,
        microsecond=0,
    )
    effective_current = current if current >= current_day_start else current - dt.timedelta(days=1)
    week_start_py = api_weekday_to_python(preferences.week_start)
    start_of_week = effective_current.replace(
        hour=preferences.day_start.hour,
        minute=preferences.day_start.minute,
        second=preferences.day_start.second,
        microsecond=0,
    ) - dt.timedelta(days=(effective_current.weekday() - week_start_py) % 7)
    end_of_window = start_of_week + dt.timedelta(days=(weeks_ahead + 1) * 7)
    return start_of_week, end_of_window


def fetch_roster_payload(config: PublicRosterConfig, start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
    payload = http_get_json(
        "/time-roster-public",
        {
            "companyId": config.company_id,
            "token": config.token,
            "startTime": start.isoformat(),
            "endTime": end.isoformat(),
        },
    )

    required_keys = {"staff", "rosteredShifts", "roles", "leaveRequests"}
    missing = required_keys.difference(payload)
    if missing:
        raise ScraperError(f"Roster payload missing keys: {sorted(missing)}")

    return payload


def company_display_name(company_name: str) -> str:
    return company_name.replace(" ", "")


def get_employee_id(payload: dict[str, Any], employee_name: str) -> str:
    staff = payload.get("staff")
    if not isinstance(staff, list):
        raise ScraperError("Roster payload must include list value for staff")

    employee = next((member for member in staff if member.get("name") == employee_name), None)
    if employee is None:
        raise ScraperError(f"Employee {employee_name!r} was not found in the public roster")

    employee_id = employee.get("id")
    if not employee_id:
        raise ScraperError(f"Employee {employee_name!r} is missing an id in the roster payload")

    return employee_id


def _parse_iso_datetime(value: Any) -> dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_datetime_flexible(value: Any, tz: dt.tzinfo) -> dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:
            v = v / 1000.0
        try:
            return dt.datetime.fromtimestamp(v, tz=dt.timezone.utc).astimezone(tz)
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        m = re.match(r"^/Date\((\d+)\)/$", s)
        if m:
            try:
                return dt.datetime.fromtimestamp(int(m.group(1)) / 1000.0, tz=dt.timezone.utc).astimezone(tz)
            except (ValueError, OSError):
                return None
        return _parse_iso_datetime(s)
    return None


def _break_start_keys() -> tuple[str, ...]:
    return (
        "startTime",
        "clockinTime",
        "start",
        "startDateTime",
        "from",
        "breakStart",
        "beginTime",
        "mealStart",
        "mealStartTime",
    )


def _break_end_keys() -> tuple[str, ...]:
    return (
        "endTime",
        "clockoutTime",
        "end",
        "endDateTime",
        "to",
        "breakEnd",
        "finishTime",
        "mealEnd",
        "mealEndTime",
    )


def _break_duration_minutes(br: dict[str, Any]) -> int | None:
    for key in ("durationMinutes", "duration", "lengthMinutes", "minutes", "breakMinutes", "durationMins"):
        if key in br and br[key] is not None:
            try:
                return int(br[key])
            except (TypeError, ValueError):
                continue
    return None


def _parse_breaks_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


def _gather_break_entries(shift_item: dict[str, Any]) -> list[Any]:
    """Collect break rows from whichever field Loaded sends (names vary by API version)."""
    out: list[Any] = []
    for key in ("breaks", "mealBreaks", "scheduledBreaks", "shiftBreaks", "rosterBreaks", "breakTimes"):
        raw = _parse_breaks_json(shift_item.get(key))
        if raw is None:
            continue
        if isinstance(raw, list):
            out.extend(raw)
        elif isinstance(raw, dict):
            out.append(raw)
    return out


def format_shift_breaks(shift_item: dict[str, Any], reference: dt.datetime) -> tuple[str, ...]:
    """Turn API break entries into display lines (start/end times or duration)."""
    entries = _gather_break_entries(shift_item)

    tz = reference.tzinfo or dt.timezone.utc
    lines: list[str] = []
    for i, br in enumerate(entries, start=1):
        if not isinstance(br, dict):
            continue
        start: dt.datetime | None = None
        end: dt.datetime | None = None
        for key in _break_start_keys():
            if key in br:
                start = _parse_datetime_flexible(br.get(key), tz)
                if start is not None:
                    break
        for key in _break_end_keys():
            if key in br:
                end = _parse_datetime_flexible(br.get(key), tz)
                if end is not None:
                    break
        if start is not None and end is not None:
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
            ls = start.astimezone(tz)
            le = end.astimezone(tz)
            if ls.date() == le.date():
                lines.append(f"Break {i}: {ls:%I:%M%p} – {le:%I:%M%p} ({ls:%A %d/%m/%Y})")
            else:
                lines.append(f"Break {i}: {ls:%I:%M%p %d/%m} – {le:%I:%M%p %d/%m}")
        else:
            duration = _break_duration_minutes(br)
            if duration is not None:
                lines.append(f"Break {i}: {duration} minutes")

    if not lines:
        for key in ("totalBreakMinutes", "scheduledBreakMinutes", "breakMinutesTotal", "totalUnpaidBreakMinutes"):
            if key not in shift_item or shift_item[key] is None:
                continue
            try:
                minutes = int(shift_item[key])
            except (TypeError, ValueError):
                continue
            if minutes > 0:
                lines.append(f"Break (scheduled): {minutes} minutes total")
                break

    return tuple(lines)


def overlapping_coworkers(payload: dict[str, Any], employee_id: str, shift: ShiftEvent) -> list[tuple[str, str]]:
    """Other staff on rostered shifts that overlap this shift; (name, role)."""
    staff = payload.get("staff")
    rostered_shifts = payload.get("rosteredShifts")
    if not isinstance(staff, list) or not isinstance(rostered_shifts, list):
        return []

    id_to_name: dict[str, str] = {}
    for member in staff:
        mid = member.get("id")
        if mid:
            id_to_name[str(mid)] = (member.get("name") or "").strip()

    seen_ids: set[str] = set()
    out: list[tuple[str, str]] = []
    for item in rostered_shifts:
        sid = item.get("staffMemberId")
        if not sid or sid == employee_id:
            continue
        start_raw = item.get("clockinTime")
        end_raw = item.get("clockoutTime")
        if not start_raw or not end_raw:
            continue
        other_start = dt.datetime.fromisoformat(start_raw)
        other_end = dt.datetime.fromisoformat(end_raw)
        if not (shift.start < other_end and shift.end > other_start):
            continue
        role_name = (item.get("roleName") or "").strip()
        if role_name.lower() not in COWORKER_ALLOWED_ROLES:
            continue
        name = id_to_name.get(str(sid), "")
        if not name:
            continue
        key = str(sid)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        out.append((name, role_name))

    out.sort(key=lambda pair: (pair[0].lower(), pair[1].lower()))
    return out


def parse_jobs(raw_jobs: Any) -> tuple[str, ...]:
    if raw_jobs in (None, "", []):
        return ()
    if isinstance(raw_jobs, list):
        return tuple(str(job).strip() for job in raw_jobs if str(job).strip())
    if isinstance(raw_jobs, str):
        try:
            decoded = json.loads(raw_jobs)
        except json.JSONDecodeError:
            decoded = [raw_jobs]
        if isinstance(decoded, list):
            return tuple(str(job).strip() for job in decoded if str(job).strip())
        if str(decoded).strip():
            return (str(decoded).strip(),)
    return (str(raw_jobs).strip(),)


def extract_employee_shifts(payload: dict[str, Any], employee_name: str) -> list[ShiftEvent]:
    rostered_shifts = payload.get("rosteredShifts")
    if not isinstance(rostered_shifts, list):
        raise ScraperError("Roster payload must include list values for staff and rosteredShifts")

    employee_id = get_employee_id(payload, employee_name)

    shifts: list[ShiftEvent] = []
    for item in rostered_shifts:
        if item.get("staffMemberId") != employee_id:
            continue
        shift_id = item.get("id")
        start_raw = item.get("clockinTime")
        end_raw = item.get("clockoutTime")
        if not shift_id or not start_raw or not end_raw:
            raise ScraperError(f"Malformed shift payload for employee {employee_name!r}: {item!r}")
        start = dt.datetime.fromisoformat(start_raw)
        end = dt.datetime.fromisoformat(end_raw)
        breaks_display = format_shift_breaks(item, start)
        shifts.append(
            ShiftEvent(
                shift_id=shift_id,
                staff_member_id=employee_id,
                staff_name=employee_name,
                role_name=(item.get("roleName") or "").strip(),
                jobs=parse_jobs(item.get("jobs")),
                breaks_display=breaks_display,
                start=start,
                end=end,
            )
        )

    shifts.sort(key=lambda shift: (shift.start, shift.shift_id))
    return shifts


def escape_ical_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold_ical_line(line: str) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    segments: list[str] = []
    current = ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > 75:
            segments.append(current)
            current = char
        else:
            current = candidate
    if current:
        segments.append(current)
    return "\r\n ".join(segments)


def make_uid(shift: ShiftEvent) -> str:
    digest = hashlib.sha256(shift.shift_id.encode("utf-8")).hexdigest()[:16]
    return f"{digest}-{shift.shift_id}@roster-scraper"


def format_utc_timestamp(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def render_event(
    shift: ShiftEvent,
    generated_at: dt.datetime,
    company_name: str,
    payload: dict[str, Any],
    employee_id: str,
) -> list[str]:
    display_name = company_display_name(company_name)
    summary = display_name
    if shift.role_name:
        summary = f"{display_name} ({shift.role_name})"

    description_parts: list[str] = []

    if shift.breaks_display:
        description_parts.extend(shift.breaks_display)
        description_parts.append("")

    coworkers = overlapping_coworkers(payload, employee_id, shift)
    if coworkers:
        description_parts.append("Working with:")
        for name, role in coworkers:
            description_parts.append(f"- {name} — {role}")
        description_parts.append("")

    description_parts.append(f"Staff: {shift.staff_name}")
    if shift.role_name:
        description_parts.append(f"Role: {shift.role_name}")
    if shift.jobs:
        description_parts.append(f"Jobs: {', '.join(shift.jobs)}")
    description_parts.append(f"Shift ID: {shift.shift_id}")
    description = escape_ical_text(chr(10).join(description_parts))
    location = escape_ical_text(LOCATION.replace("\n", chr(10)))

    lines = [
        "BEGIN:VEVENT",
        f"UID:{make_uid(shift)}",
        f"DTSTAMP:{format_utc_timestamp(generated_at)}",
        f"DTSTART:{format_utc_timestamp(shift.start)}",
        f"DTEND:{format_utc_timestamp(shift.end)}",
        f"SUMMARY:{escape_ical_text(summary)}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{location}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "END:VEVENT",
    ]
    return [fold_ical_line(line) for line in lines]


def render_calendar(
    shifts: list[ShiftEvent],
    company_name: str,
    payload: dict[str, Any],
    employee_id: str,
    generated_at: dt.datetime | None = None,
) -> str:
    generated_at = generated_at or dt.datetime.now(dt.timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ical_text(CALENDAR_NAME)}",
        f"X-WR-TIMEZONE:{escape_ical_text('Pacific/Auckland')}",
    ]
    for shift in shifts:
        lines.extend(render_event(shift, generated_at, company_name, payload, employee_id))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def render_summary(shifts: list[ShiftEvent], company_name: str) -> str:
    if not shifts:
        return "No upcoming shifts found.\n"

    lines = []
    display_name = company_display_name(company_name)
    for shift in shifts:
        local_start = shift.start.astimezone(ZoneInfo("Pacific/Auckland"))
        local_end = shift.end.astimezone(ZoneInfo("Pacific/Auckland"))
        lines.append(f"Date: {local_start:%A, %d/%m/%Y}")
        title = display_name if not shift.role_name else f"{display_name} ({shift.role_name})"
        lines.append(f"Event name: {title}")
        lines.append(f"Time: {local_start:%I:%M%p} -> {local_end:%I:%M%p}")
        if shift.jobs:
            lines.append(f"Jobs: {', '.join(shift.jobs)}")
        lines.append("-" * 40)
    return "\n".join(lines) + "\n"


def write_outputs(calendar_text: str, summary_text: str) -> None:
    OUTPUT_PATH.write_text(calendar_text, encoding="utf-8", newline="")
    SUMMARY_PATH.write_text(summary_text, encoding="utf-8", newline="")
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_OUTPUT_PATH.write_text(calendar_text, encoding="utf-8", newline="")
    PUBLIC_INDEX_PATH.write_text(
        "\n".join(
            [
                "<!doctype html>",
                "<html lang=\"en\">",
                "<head>",
                "  <meta charset=\"utf-8\">",
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
                f"  <title>{CALENDAR_NAME}</title>",
                "</head>",
                "<body>",
                f"  <p><a href=\"roster.ics\">Download {CALENDAR_NAME}</a></p>",
                "</body>",
                "</html>",
                "",
            ]
        ),
        encoding="utf-8",
        newline="",
    )
    PUBLIC_NOJEKYLL_PATH.write_text("", encoding="utf-8")


def main() -> int:
    public_roster_url, employee_name, weeks_ahead = load_settings()
    config = parse_public_roster_url(public_roster_url)
    preferences = fetch_preferences(config)
    start, end = calculate_window(preferences, weeks_ahead=weeks_ahead)
    payload = fetch_roster_payload(config, start, end)
    shifts = extract_employee_shifts(payload, employee_name)
    employee_id = get_employee_id(payload, employee_name)
    company_name = preferences.company_name.strip() or "Roster"
    calendar_dtstamp = start.astimezone(dt.timezone.utc)
    calendar_text = render_calendar(shifts, company_name, payload, employee_id, generated_at=calendar_dtstamp)
    summary_text = render_summary(shifts, company_name)
    write_outputs(calendar_text, summary_text)
    print(
        f"Generated {OUTPUT_PATH} for {employee_name}: {len(shifts)} shift(s) "
        f"between {start.isoformat()} and {end.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScraperError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
