#!/usr/bin/env python3
"""Fetch an iCalendar (ICS) feed and print the events of the coming days as JSON.

Usage: agenda-feed.py <https-url> <days-ahead>

Standard library only. Handles what Outlook / Microsoft 365 publishes:
Windows time zone names described by VTIMEZONE blocks, weekly/monthly/yearly
RRULEs, EXDATE and moved or edited occurrences (RECURRENCE-ID).

The feed is cached under $XDG_CACHE_HOME so the agenda still shows when the
network is down; the reply then carries "stale": true.

Always prints exactly one JSON line on stdout and exits 0, so the caller only
has to parse it. Nothing from the feed is ever executed or passed to a shell.
"""

import calendar
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

MAX_FEED_BYTES = 30 * 1024 * 1024
MAX_EVENTS = 400
MAX_TEXT = 200
FETCH_TIMEOUT = 25

UTC = dt.timezone.utc

JOIN_PATTERNS = [
    r"https://teams\.microsoft\.com/l/meetup-join/[^\s<>\"']+",
    r"https://teams\.live\.com/meet/[^\s<>\"']+",
    r"https://(?:[a-z0-9-]+\.)?zoom\.us/(?:j|my|w)/[^\s<>\"']+",
    r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:\?[^\s<>\"']*)?",
    r"https://[a-z0-9-]+\.webex\.com/[^\s<>\"']+",
    r"https://whereby\.com/[^\s<>\"']+",
]
JOIN_RE = re.compile("|".join(JOIN_PATTERNS), re.IGNORECASE)

CANCELLED_PREFIXES = ("annulé", "annule", "canceled", "cancelled", "abgesagt", "cancelado", "annullato")

DAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def reply(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    sys.exit(0)


def fail(code, detail=""):
    reply({"ok": False, "error": code, "detail": str(detail)[:200]})


# ---------------------------------------------------------------- fetching

def cache_path(url):
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    folder = os.path.join(base, "omarchy-agenda")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return folder, os.path.join(folder, digest + ".ics")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "omarchy-agenda/1.1", "Accept": "text/calendar"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        data = resp.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("feed too large")
    if b"BEGIN:VCALENDAR" not in data[:4096]:
        raise ValueError("not an iCalendar feed")
    return data


def load_feed(url):
    folder, path = cache_path(url)
    try:
        data = fetch(url)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return data, time.time(), False, ""
    except Exception as exc:  # network down, HTTP error, bad content
        reason = exc.__class__.__name__
        if isinstance(exc, urllib.error.HTTPError):
            reason = "HTTP %d" % exc.code
        elif isinstance(exc, urllib.error.URLError):
            reason = str(exc.reason)
        elif isinstance(exc, ValueError):
            reason = str(exc)
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_FEED_BYTES + 1)
            return data, os.path.getmtime(path), True, reason
        except OSError:
            fail("fetchFailed", reason)


# ---------------------------------------------------------------- parsing

def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def split_property(line):
    """'NAME;P1=a;P2="b,c":value' -> (NAME, {P1: a, P2: 'b,c'}, value)."""
    in_quotes = False
    colon = -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            colon = i
            break
    if colon < 0:
        return None
    head, value = line[:colon], line[colon + 1:]
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    if not parts:
        return None
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def unescape(value):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def parse_components(lines):
    """Returns a nested tree of {'name', 'props': [(name, params, value)], 'children'}."""
    root = {"name": "ROOT", "props": [], "children": []}
    stack = [root]
    for line in lines:
        if not line:
            continue
        parsed = split_property(line)
        if not parsed:
            continue
        name, params, value = parsed
        if name == "BEGIN":
            comp = {"name": value.strip().upper(), "props": [], "children": []}
            stack[-1]["children"].append(comp)
            stack.append(comp)
        elif name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]["props"].append((name, params, value))
    return root


def first(comp, name):
    for n, params, value in comp["props"]:
        if n == name:
            return params, value
    return None


def all_props(comp, name):
    return [(p, v) for n, p, v in comp["props"] if n == name]


# ---------------------------------------------------------------- recurrence

def parse_rrule(value):
    rule = {}
    for part in value.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            rule[k.upper()] = v
    return rule


def parse_byday(value):
    """'MO,-1SU,2TU' -> [(None, 0), (-1, 6), (2, 1)]."""
    out = []
    for item in (value or "").split(","):
        m = re.fullmatch(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)", item.strip().upper())
        if m:
            out.append((int(m.group(1)) if m.group(1) else None, DAY_CODES[m.group(2)]))
    return out


def int_list(value):
    out = []
    for item in (value or "").split(","):
        try:
            out.append(int(item))
        except ValueError:
            pass
    return out


def nth_weekday_days(year, month, weekday, nth):
    """Days of `month` falling on `weekday`; only the nth one (1-based, negative from the end) when given."""
    ndays = calendar.monthrange(year, month)[1]
    days = [d for d in range(1, ndays + 1) if dt.date(year, month, d).weekday() == weekday]
    if nth is None:
        return days
    idx = nth - 1 if nth > 0 else nth
    return [days[idx]] if -len(days) <= idx < len(days) else []


def month_days(year, month, rule, default_day):
    ndays = calendar.monthrange(year, month)[1]
    days = set()
    bymonthday = int_list(rule.get("BYMONTHDAY"))
    byday = parse_byday(rule.get("BYDAY"))
    if bymonthday:
        for d in bymonthday:
            d = d if d > 0 else ndays + d + 1
            if 1 <= d <= ndays:
                days.add(d)
        if byday:
            wanted = {w for _, w in byday}
            days = {d for d in days if dt.date(year, month, d).weekday() in wanted}
    elif byday:
        for nth, weekday in byday:
            days.update(nth_weekday_days(year, month, weekday, nth))
    elif 1 <= default_day <= ndays:
        days.add(default_day)
    days = sorted(days)
    setpos = int_list(rule.get("BYSETPOS"))
    if setpos:
        days = sorted({days[p - 1 if p > 0 else p] for p in setpos if -len(days) <= (p - 1 if p > 0 else p) < len(days)})
    return days


def expand(start, rule, until_local, limit_local, max_steps=6000):
    """Yields naive local datetimes of a recurrence, in order, starting at `start`.

    `until_local` is the RRULE UNTIL already converted to the event's local time
    (or None); expansion stops after `limit_local`.
    """
    freq = rule.get("FREQ", "").upper()
    try:
        interval = max(1, int(rule.get("INTERVAL", "1")))
    except ValueError:
        interval = 1
    try:
        count = int(rule["COUNT"]) if "COUNT" in rule else None
    except ValueError:
        count = None
    bymonth = int_list(rule.get("BYMONTH"))
    byday = parse_byday(rule.get("BYDAY"))
    wkst = DAY_CODES.get(rule.get("WKST", "MO").upper(), 0)
    tod = start.time()
    emitted = 0

    def accept(candidate):
        return candidate >= start and (until_local is None or candidate <= until_local)

    def periods():
        if freq == "DAILY":
            day = start.date()
            while True:
                yield [day]
                day += dt.timedelta(days=interval)
        elif freq == "WEEKLY":
            week_start = start.date() - dt.timedelta(days=(start.weekday() - wkst) % 7)
            weekdays = sorted({w for _, w in byday}, key=lambda w: (w - wkst) % 7) or [start.weekday()]
            while True:
                yield [week_start + dt.timedelta(days=(w - wkst) % 7) for w in weekdays]
                week_start += dt.timedelta(weeks=interval)
        elif freq == "MONTHLY":
            year, month = start.year, start.month
            while True:
                if not bymonth or month in bymonth:
                    yield [dt.date(year, month, d) for d in month_days(year, month, rule, start.day)]
                else:
                    yield []
                month += interval
                year += (month - 1) // 12
                month = (month - 1) % 12 + 1
        elif freq == "YEARLY":
            year = start.year
            months = bymonth or [start.month]
            while True:
                days = []
                for month in months:
                    if byday or rule.get("BYMONTHDAY"):
                        days += [dt.date(year, month, d) for d in month_days(year, month, rule, start.day)]
                    elif start.day <= calendar.monthrange(year, month)[1]:
                        days.append(dt.date(year, month, start.day))
                yield sorted(days)
                year += interval
        else:
            yield [start.date()]

    steps = 0
    for days in periods():
        steps += 1
        if steps > max_steps:
            return
        for day in days:
            if freq == "DAILY" and byday and day.weekday() not in {w for _, w in byday}:
                continue
            if freq == "DAILY" and bymonth and day.month not in bymonth:
                continue
            candidate = dt.datetime.combine(day, tod)
            if candidate > limit_local or (until_local is not None and candidate > until_local):
                return
            if not accept(candidate):
                continue
            yield candidate
            emitted += 1
            if count is not None and emitted >= count:
                return
        if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            return


# ---------------------------------------------------------------- time zones

def parse_offset(value):
    m = re.fullmatch(r"([+-])(\d{2})(\d{2})(\d{2})?", (value or "").strip())
    if not m:
        return None
    seconds = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4) or 0)
    return dt.timedelta(seconds=seconds if m.group(1) == "+" else -seconds)


def parse_naive(value):
    value = value.strip()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?(Z)?", value)
    if not m:
        return None, False, False
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if m.group(4) is None:
        return dt.datetime(y, mo, d), True, False
    return dt.datetime(y, mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)), False, bool(m.group(7))


class VTimezone:
    """A time zone described by an ICS VTIMEZONE (as Outlook publishes them)."""

    def __init__(self, comp):
        self.observances = []
        for child in comp["children"]:
            if child["name"] not in ("STANDARD", "DAYLIGHT"):
                continue
            start = first(child, "DTSTART")
            offset_to = first(child, "TZOFFSETTO")
            if not start or not offset_to:
                continue
            naive, _, _ = parse_naive(start[1])
            offset = parse_offset(offset_to[1])
            if naive is None or offset is None:
                continue
            rrule = first(child, "RRULE")
            self.observances.append((naive, offset, parse_rrule(rrule[1]) if rrule else None))

    def offset(self, local):
        best = None
        for start, offset, rule in self.observances:
            if rule is None:
                candidates = [start]
            else:
                # Transitions of the previous and current year; the latest one
                # before `local` decides the offset.
                candidates = []
                months = int_list(rule.get("BYMONTH")) or [start.month]
                for year in (local.year - 1, local.year):
                    for month in months:
                        for day in month_days(year, month, rule, start.day):
                            candidates.append(dt.datetime.combine(dt.date(year, month, day), start.time()))
            for c in candidates:
                if c <= local and (best is None or c > best[0]):
                    best = (c, offset)
        if best is None:
            return self.observances[0][1] if self.observances else dt.timedelta(0)
        return best[1]

    def to_utc(self, local):
        return (local - self.offset(local)).replace(tzinfo=UTC)


class Zones:
    def __init__(self, root):
        self.vtimezones = {}
        for comp in iter_components(root, "VTIMEZONE"):
            tzid = first(comp, "TZID")
            if tzid:
                tz = VTimezone(comp)
                if tz.observances:
                    self.vtimezones[unescape(tzid[1]).strip()] = tz

    def to_utc(self, local, tzid):
        """Naive local time in `tzid` (None = floating) -> aware UTC datetime."""
        if tzid:
            tz = self.vtimezones.get(tzid)
            if tz:
                return tz.to_utc(local)
            try:
                from zoneinfo import ZoneInfo
                return local.replace(tzinfo=ZoneInfo(tzid)).astimezone(UTC)
            except Exception:
                pass
        return local.astimezone(UTC)  # floating or unknown zone: system local time

    def from_utc(self, utc, tzid):
        """Aware UTC -> naive local time in `tzid` (used for UNTIL)."""
        guess = utc.replace(tzinfo=None)
        for _ in range(3):
            back = self.to_utc(guess, tzid)
            delta = utc - back
            if delta == dt.timedelta(0):
                break
            guess += delta
        return guess


def iter_components(comp, name):
    for child in comp["children"]:
        if child["name"] == name:
            yield child
        yield from iter_components(child, name)


# ---------------------------------------------------------------- events

def date_prop(comp, name, zones):
    """-> (naive local, tzid or None, all_day, utc-aware) or None."""
    found = first(comp, name)
    if not found:
        return None
    params, value = found
    naive, all_day, is_utc = parse_naive(value.split(",")[0])
    if naive is None:
        return None
    if params.get("VALUE", "").upper() == "DATE":
        all_day = True
    tzid = None if is_utc or all_day else params.get("TZID")
    if is_utc:
        utc = naive.replace(tzinfo=UTC)
    elif all_day:
        utc = naive.astimezone(UTC)
    else:
        utc = zones.to_utc(naive, tzid)
    return naive, tzid, all_day, utc


def parse_duration(value):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", (value or "").strip())
    if not m:
        return None
    delta = dt.timedelta(weeks=int(m.group(2) or 0), days=int(m.group(3) or 0), hours=int(m.group(4) or 0),
                         minutes=int(m.group(5) or 0), seconds=int(m.group(6) or 0))
    return -delta if m.group(1) == "-" else delta


def clean_text(value, limit=MAX_TEXT):
    text = unescape(value or "")
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def join_url(comp):
    sources = []
    for name in ("X-MICROSOFT-SKYPETEAMSMEETINGURL", "X-MICROSOFT-ONLINEMEETINGCONFLINK", "URL", "LOCATION", "DESCRIPTION", "X-ALT-DESC"):
        for _, value in all_props(comp, name):
            sources.append(unescape(value))
    for text in sources:
        m = JOIN_RE.search(text)
        if m:
            url = m.group(0).rstrip(".,;)]>\\")
            if len(url) <= 2000:
                return url
    return ""


def occurrence_key(utc, all_day, naive):
    return naive.strftime("%Y%m%d") if all_day else utc.strftime("%Y%m%dT%H%M%SZ")


def event_record(comp, start_utc, end_utc, all_day, start_naive, end_naive):
    summary = first(comp, "SUMMARY")
    title = clean_text(summary[1]) if summary else ""
    location = first(comp, "LOCATION")
    status = first(comp, "STATUS")
    busy = first(comp, "X-MICROSOFT-CDO-BUSYSTATUS")
    transp = first(comp, "TRANSP")
    cancelled = bool(status and status[1].strip().upper() == "CANCELLED") or title.lower().startswith(CANCELLED_PREFIXES)
    busy_status = busy[1].strip().upper() if busy else ("FREE" if transp and transp[1].strip().upper() == "TRANSPARENT" else "BUSY")
    if busy_status not in ("BUSY", "FREE", "TENTATIVE", "OOF", "WORKINGELSEWHERE"):
        busy_status = "BUSY"
    record = {
        "title": title,
        "location": clean_text(location[1]) if location else "",
        "allDay": all_day,
        "cancelled": cancelled,
        "busy": busy_status,
        "joinUrl": join_url(comp),
    }
    if all_day:
        # All-day events keep their calendar dates, independent of time zones.
        record["startDate"] = start_naive.strftime("%Y-%m-%d")
        record["endDate"] = end_naive.strftime("%Y-%m-%d")
        record["start"] = int(start_naive.timestamp())
        record["end"] = int(end_naive.timestamp())
    else:
        record["start"] = int(start_utc.timestamp())
        record["end"] = int(end_utc.timestamp())
    return record


def collect(root, window_start, window_end):
    zones = Zones(root)
    events = list(iter_components(root, "VEVENT"))
    overrides = {}
    masters = []
    for comp in events:
        uid = first(comp, "UID")
        uid = uid[1].strip() if uid else ""
        rid = date_prop(comp, "RECURRENCE-ID", zones)
        if rid and uid:
            naive, _, all_day, utc = rid
            overrides[(uid, occurrence_key(utc, all_day, naive))] = comp
        else:
            masters.append((uid, comp))

    out = []

    def add(comp, start, end_naive_or_delta):
        naive, tzid, all_day, utc = start
        if isinstance(end_naive_or_delta, dt.timedelta):
            end_naive = naive + end_naive_or_delta
        else:
            end_naive = end_naive_or_delta
        if all_day:
            end_naive = max(end_naive, naive + dt.timedelta(days=1))
            end_utc = end_naive.astimezone(UTC)
        else:
            end_utc = zones.to_utc(end_naive, tzid)
            if end_utc < utc:
                end_utc = utc
        if end_utc <= window_start or utc >= window_end:
            return
        if all_day and end_utc == utc:
            return
        out.append(event_record(comp, utc, end_utc, all_day, naive, end_naive))

    def duration_of(comp, start):
        naive, tzid, all_day, _ = start
        end = date_prop(comp, "DTEND", zones)
        if end:
            return end[0] - naive
        dur = first(comp, "DURATION")
        if dur:
            parsed = parse_duration(dur[1])
            if parsed is not None:
                return parsed
        return dt.timedelta(days=1) if all_day else dt.timedelta(0)

    for uid, comp in masters:
        start = date_prop(comp, "DTSTART", zones)
        if not start:
            continue
        naive, tzid, all_day, utc = start
        duration = duration_of(comp, start)
        rrule = first(comp, "RRULE")
        if not rrule:
            add(comp, start, duration)
            continue
        rule = parse_rrule(rrule[1])
        until_local = None
        if "UNTIL" in rule:
            u_naive, u_all_day, u_is_utc = parse_naive(rule["UNTIL"])
            if u_naive is not None:
                if u_all_day:
                    until_local = u_naive + dt.timedelta(days=1) - dt.timedelta(seconds=1)
                elif u_is_utc and not all_day:
                    until_local = zones.from_utc(u_naive.replace(tzinfo=UTC), tzid)
                else:
                    until_local = u_naive
        exdates = set()
        for params, value in all_props(comp, "EXDATE"):
            for item in value.split(","):
                ex_naive, ex_all_day, ex_is_utc = parse_naive(item)
                if ex_naive is None:
                    continue
                if all_day or ex_all_day:
                    exdates.add(ex_naive.strftime("%Y%m%d"))
                else:
                    ex_utc = ex_naive.replace(tzinfo=UTC) if ex_is_utc else zones.to_utc(ex_naive, params.get("TZID") or tzid)
                    exdates.add(ex_utc.strftime("%Y%m%dT%H%M%SZ"))
        limit_local = (window_end + dt.timedelta(days=2)).astimezone().replace(tzinfo=None)
        for occ in expand(naive, rule, until_local, limit_local):
            occ_utc = occ.astimezone(UTC) if all_day else zones.to_utc(occ, tzid)
            key = occurrence_key(occ_utc, all_day, occ)
            if key in exdates:
                continue
            override = overrides.pop((uid, key), None)
            if override is not None:
                o_start = date_prop(override, "DTSTART", zones)
                if o_start:
                    add(override, o_start, duration_of(override, o_start))
                continue
            add(comp, (occ, tzid, all_day, occ_utc), duration)

    # Edited occurrences whose master is missing or does not generate them.
    for (uid, _), comp in overrides.items():
        start = date_prop(comp, "DTSTART", zones)
        if start:
            add(comp, start, duration_of(comp, start))

    out.sort(key=lambda e: (e["start"], not e["allDay"], e["end"], e["title"]))
    return out[:MAX_EVENTS]


def main(argv):
    if len(argv) != 3:
        fail("usage")
    url = argv[1].strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url:
        fail("noUrl")
    if not re.fullmatch(r"https://[^\s]{4,2040}", url):
        fail("badUrl")
    try:
        days_ahead = max(1, min(60, int(argv[2])))
    except ValueError:
        days_ahead = 7

    data, fetched_at, stale, reason = load_feed(url)
    try:
        text = data.decode("utf-8", errors="replace")
        root = parse_components(unfold(text))
    except Exception as exc:
        fail("parseFailed", exc.__class__.__name__)

    now = dt.datetime.now().astimezone()
    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    window_end = (now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=days_ahead)).astimezone(UTC)
    try:
        events = collect(root, window_start, window_end)
    except Exception as exc:
        fail("parseFailed", "%s: %s" % (exc.__class__.__name__, exc))

    cal_name = ""
    for comp in iter_components(root, "VCALENDAR"):
        name = first(comp, "X-WR-CALNAME")
        if name:
            cal_name = clean_text(name[1], 80)
        break

    reply({
        "ok": True,
        "stale": stale,
        "staleReason": reason[:200] if stale else "",
        "fetchedAt": int(fetched_at),
        "calendarName": cal_name,
        "events": events,
    })


if __name__ == "__main__":
    main(sys.argv)
