import datetime as dt
import json
import unittest
from pathlib import Path

import scraper

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "roster_payload.json"


class ParsePublicRosterUrlTests(unittest.TestCase):
    def test_parses_valid_public_roster_url(self):
        config = scraper.parse_public_roster_url(
            "https://loadedhub.com/App/PublicRoster#/roster/company-123/token-456"
        )
        self.assertEqual(config.company_id, "company-123")
        self.assertEqual(config.token, "token-456")

    def test_rejects_missing_token(self):
        with self.assertRaises(scraper.ScraperError):
            scraper.parse_public_roster_url(
                "https://loadedhub.com/App/PublicRoster#/roster/company-123"
            )

    def test_rejects_wrong_fragment(self):
        with self.assertRaises(scraper.ScraperError):
            scraper.parse_public_roster_url(
                "https://loadedhub.com/App/PublicRoster#/wrong/company-123/token-456"
            )


class WindowCalculationTests(unittest.TestCase):
    def test_calculates_five_week_window_from_current_roster_week(self):
        preferences = scraper.Preferences(
            week_start=1,
            day_start=dt.time(5, 0, 0),
            timezone="Pacific/Auckland",
            company_name="Chou Chou",
        )
        now = dt.datetime(2026, 3, 10, 4, 30, tzinfo=dt.timezone(dt.timedelta(hours=13)))
        start, end = scraper.calculate_window(preferences, now=now, weeks_ahead=4)
        self.assertEqual(start.isoformat(), "2026-03-09T05:00:00+13:00")
        self.assertEqual(end.isoformat(), "2026-04-13T05:00:00+12:00")


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_extracts_employee_shifts_sorted_by_start_then_id(self):
        shifts = scraper.extract_employee_shifts(self.payload, "Cristian Rus")
        self.assertEqual([shift.shift_id for shift in shifts], ["shift-001", "shift-002"])

    def test_returns_empty_list_when_employee_has_no_shifts(self):
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        payload["rosteredShifts"] = [shift for shift in payload["rosteredShifts"] if shift["staffMemberId"] != "staff-cristian"]
        shifts = scraper.extract_employee_shifts(payload, "Cristian Rus")
        self.assertEqual(shifts, [])

    def test_raises_when_employee_is_missing(self):
        with self.assertRaises(scraper.ScraperError):
            scraper.extract_employee_shifts(self.payload, "Missing Person")

    def test_raises_on_malformed_payload(self):
        with self.assertRaises(scraper.ScraperError):
            scraper.extract_employee_shifts({"staff": "bad", "rosteredShifts": []}, "Cristian Rus")


class CalendarRenderingTests(unittest.TestCase):
    def setUp(self):
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.shifts = scraper.extract_employee_shifts(payload, "Cristian Rus")
        self.generated_at = dt.datetime(2026, 3, 9, 0, 0, tzinfo=dt.timezone.utc)

    def test_renders_stable_calendar(self):
        calendar_text = scraper.render_calendar(self.shifts, "Chou Chou", generated_at=self.generated_at)
        self.assertIn("BEGIN:VCALENDAR\r\n", calendar_text)
        self.assertIn("UID:", calendar_text)
        self.assertEqual(calendar_text, scraper.render_calendar(self.shifts, "Chou Chou", generated_at=self.generated_at))

    def test_renders_overnight_shift_end_correctly(self):
        calendar_text = scraper.render_calendar(self.shifts, "Chou Chou", generated_at=self.generated_at)
        self.assertIn("DTSTART:20260316T090000Z", calendar_text)
        self.assertIn("DTEND:20260316T130000Z", calendar_text)

    def test_renders_empty_calendar(self):
        calendar_text = scraper.render_calendar([], "Chou Chou", generated_at=self.generated_at)
        self.assertIn("BEGIN:VCALENDAR", calendar_text)
        self.assertNotIn("BEGIN:VEVENT", calendar_text)

    def test_escapes_text(self):
        escaped = scraper.escape_ical_text("Hello, world;\nLine 2")
        self.assertEqual(escaped, "Hello\\, world\\;\\nLine 2")


if __name__ == "__main__":
    unittest.main()
