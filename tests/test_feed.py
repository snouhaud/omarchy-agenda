"""Regression tests for agenda-feed.py, on a synthetic Outlook-style feed.

No network: the parser functions are called directly.
    python3 -I tests/test_feed.py
"""

import datetime as dt
import importlib.util
import os
import sys
import unittest
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("feed", os.path.join(HERE, "..", "agenda-feed.py"))
feed = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(feed)

UTC = dt.timezone.utc
PARIS = ZoneInfo("Europe/Paris")

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Romance Standard Time
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:Paris\\, Madrid
BEGIN:STANDARD
DTSTART:16010101T020000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T010000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE"""

FEED = """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:Test
""" + VTIMEZONE + """
BEGIN:VEVENT
UID:weekly-1
SUMMARY:Weekly sync
LOCATION:Réunion Microsoft Teams
DESCRIPTION:Join: <https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=x>
DTSTART;TZID=Romance Standard Time:20261019T100000
DTEND;TZID=Romance Standard Time:20261019T103000
RRULE:FREQ=WEEKLY;UNTIL=20261207T090000Z;INTERVAL=1;BYDAY=MO;WKST=MO
EXDATE;TZID=Romance Standard Time:20261109T100000
X-MICROSOFT-CDO-BUSYSTATUS:BUSY
END:VEVENT
BEGIN:VEVENT
UID:weekly-1
RECURRENCE-ID;TZID="Paris, Madrid":20261116T100000
SUMMARY:Weekly sync (moved)
DTSTART;TZID="Paris, Madrid":20261116T150000
DTEND;TZID="Paris, Madrid":20261116T153000
X-MICROSOFT-CDO-BUSYSTATUS:TENTATIVE
END:VEVENT
BEGIN:VEVENT
UID:allday-1
SUMMARY:Conference
DTSTART;VALUE=DATE:20261117
DTEND;VALUE=DATE:20261119
X-MICROSOFT-CDO-BUSYSTATUS:OOF
END:VEVENT
BEGIN:VEVENT
UID:cancel-1
SUMMARY:Annulé: Old meeting
DTSTART:20261118T080000Z
DTEND:20261118T090000Z
LOCATION:Room 1\\; https://zoom.us/j/123456789
END:VEVENT
BEGIN:VEVENT
UID:markup-1
SUMMARY:<img src="https://example.invalid/x"> \\, tricky\\; title
DTSTART:20261118T120000Z
DTEND:20261118T130000Z
END:VEVENT
END:VCALENDAR
"""


def events_between(start, end, text=FEED):
    root = feed.parse_components(feed.unfold(text.replace("\n", "\r\n")))
    return feed.collect(root, start.astimezone(UTC), end.astimezone(UTC))


def local(ts):
    return dt.datetime.fromtimestamp(ts, PARIS)


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.events = events_between(dt.datetime(2026, 10, 1, tzinfo=PARIS), dt.datetime(2026, 12, 31, tzinfo=PARIS))
        self.weekly = [e for e in self.events if e["title"].startswith("Weekly sync")]

    def test_weekly_occurrences_keep_wall_clock_time_across_dst(self):
        starts = [local(e["start"]) for e in self.weekly]
        # 19/10 is summer time (UTC+2), 26/10 onwards winter time (UTC+1).
        self.assertEqual(starts[0], dt.datetime(2026, 10, 19, 10, 0, tzinfo=PARIS))
        self.assertEqual(starts[1], dt.datetime(2026, 10, 26, 10, 0, tzinfo=PARIS))
        self.assertEqual(starts[0].utcoffset(), dt.timedelta(hours=2))
        self.assertEqual(starts[1].utcoffset(), dt.timedelta(hours=1))

    def test_until_exdate_and_override(self):
        days = [local(e["start"]).strftime("%m-%d %H:%M") for e in self.weekly]
        self.assertNotIn("11-09 10:00", days)            # EXDATE
        self.assertIn("11-16 15:00", days)               # moved occurrence
        self.assertNotIn("11-16 10:00", days)
        self.assertEqual(days[-1], "12-07 10:00")        # UNTIL is inclusive
        moved = [e for e in self.weekly if e["title"] == "Weekly sync (moved)"][0]
        self.assertEqual(moved["busy"], "TENTATIVE")

    def test_join_url_from_description(self):
        self.assertTrue(self.weekly[0]["joinUrl"].startswith("https://teams.microsoft.com/l/meetup-join/"))
        self.assertNotIn(">", self.weekly[0]["joinUrl"])

    def test_all_day_event_keeps_its_dates(self):
        conf = [e for e in self.events if e["title"] == "Conference"][0]
        self.assertTrue(conf["allDay"])
        self.assertEqual((conf["startDate"], conf["endDate"]), ("2026-11-17", "2026-11-19"))
        self.assertEqual(conf["busy"], "OOF")

    def test_cancelled_prefix_and_zoom_link_in_location(self):
        old = [e for e in self.events if e["title"].startswith("Annulé")][0]
        self.assertTrue(old["cancelled"])
        self.assertEqual(old["joinUrl"], "https://zoom.us/j/123456789")

    def test_markup_is_kept_as_plain_text(self):
        tricky = [e for e in self.events if "tricky" in e["title"]][0]
        # The parser only unescapes; QML shows it with Text.PlainText.
        self.assertEqual(tricky["title"], '<img src="https://example.invalid/x"> , tricky; title')

    def test_window_filtering(self):
        week = events_between(dt.datetime(2026, 11, 16, tzinfo=PARIS), dt.datetime(2026, 11, 17, tzinfo=PARIS))
        self.assertEqual([e["title"] for e in week], ["Weekly sync (moved)"])

    def test_vtimezone_matches_zoneinfo(self):
        root = feed.parse_components(feed.unfold(FEED))
        zones = feed.Zones(root)
        t = dt.datetime(2025, 1, 1, 0, 30)
        while t < dt.datetime(2028, 1, 1):
            if not (t.month in (3, 10) and t.hour in (1, 2, 3)):
                for tzid in ("Romance Standard Time", "Paris, Madrid"):
                    self.assertEqual(zones.to_utc(t, tzid), t.replace(tzinfo=PARIS).astimezone(UTC), (tzid, t))
            t += dt.timedelta(hours=7)

    def test_rrule_variants(self):
        s = dt.datetime(2026, 1, 2, 9, 0)
        far = dt.datetime(2030, 1, 1)

        def days(rule, until=None, fmt="%Y-%m-%d"):
            return [d.strftime(fmt) for d in feed.expand(s, feed.parse_rrule(rule), until, far)]

        self.assertEqual(days("FREQ=WEEKLY;INTERVAL=2;BYDAY=FR;UNTIL=20260215T000000Z", dt.datetime(2026, 2, 15)),
                         ["2026-01-02", "2026-01-16", "2026-01-30", "2026-02-13"])
        self.assertEqual(days("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=3"),
                         ["2026-01-30", "2026-02-27", "2026-03-31"])
        self.assertEqual(days("FREQ=MONTHLY;BYDAY=2TU;COUNT=2"), ["2026-01-13", "2026-02-10"])
        self.assertEqual(days("FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3;COUNT=2"), ["2026-03-29", "2027-03-28"])
        self.assertEqual(days("FREQ=DAILY;COUNT=3;BYDAY=MO,TU,WE,TH,FR"), ["2026-01-02", "2026-01-05", "2026-01-06"])

    def run_helper(self, args, stdin):
        import subprocess
        script = os.path.join(HERE, "..", "agenda-feed.py")
        return subprocess.run([sys.executable, "-I", script, *args], input=stdin,
                              capture_output=True, text=True, timeout=15).stdout

    def test_bad_url_is_rejected(self):
        out = self.run_helper(["7"], '{"url": "http://example.invalid/cal.ics"}\n')
        self.assertIn('"error":"badUrl"', out)

    def test_url_is_not_accepted_in_argv(self):
        # The old argv form must fail, so the secret link cannot leak there.
        out = self.run_helper(["https://example.invalid/cal.ics", "7"], "")
        self.assertIn('"error":"usage"', out)
        out = self.run_helper(["7"], '"https://example.invalid/cal.ics"\n')
        self.assertIn('"error":"usage"', out)


class CacheTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "omarchy-agenda")
        self.path = os.path.join(self.folder, "feed.ics")

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_is_private(self):
        feed.write_cache(self.folder, self.path, b"BEGIN:VCALENDAR")
        self.assertEqual(os.stat(self.folder).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(feed.read_cache(self.folder, self.path)[0], b"BEGIN:VCALENDAR")
        self.assertEqual(os.listdir(self.folder), ["feed.ics"])

    def test_open_folder_is_tightened(self):
        os.mkdir(self.folder, 0o777)
        os.chmod(self.folder, 0o777)
        feed.write_cache(self.folder, self.path, b"x")
        self.assertEqual(os.stat(self.folder).st_mode & 0o777, 0o700)

    def test_symlinked_folder_is_refused(self):
        elsewhere = os.path.join(self.tmp.name, "elsewhere")
        os.mkdir(elsewhere)
        os.symlink(elsewhere, self.folder)
        with self.assertRaises(PermissionError):
            feed.write_cache(self.folder, self.path, b"x")
        self.assertEqual(os.listdir(elsewhere), [])

    def test_planted_symlinks_are_not_followed(self):
        victim = os.path.join(self.tmp.name, "victim")
        with open(victim, "wb") as f:
            f.write(b"keep")
        os.mkdir(self.folder, 0o700)
        # A planted cache file is replaced, not written through.
        os.symlink(victim, self.path)
        feed.write_cache(self.folder, self.path, b"new")
        with open(victim, "rb") as f:
            self.assertEqual(f.read(), b"keep")
        self.assertFalse(os.path.islink(self.path))
        # And a symlink is never read as the cache.
        os.unlink(self.path)
        os.symlink(victim, self.path)
        with self.assertRaises(OSError):
            feed.read_cache(self.folder, self.path)


if __name__ == "__main__":
    unittest.main(verbosity=1)
