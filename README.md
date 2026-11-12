# Agenda

An [Omarchy](https://omarchy.org) bar widget that shows your next meeting next
to the clock and, on click, the agenda of the coming days — a bit like
Itsycal on macOS. It reads a published iCalendar (ICS) link, so it works with
Outlook / Microsoft 365 without signing in, and with Google Calendar, iCloud
or any other calendar that can publish an ICS feed.

- **In the bar**: `14:00 Project review`, then `Project review in 25 min` in
  the last hour, and `Project review · until 15:00` while it runs. The label
  turns to the alert color a few minutes before a meeting starts.
- **Popup**: today and the next days with events, grouped by day. Past events
  are dimmed, tentative ones in italics, cancelled ones struck through, the
  current one highlighted.
- **Join button** for Teams, Zoom, Google Meet, Webex and Whereby links found
  in the event (location, description or Outlook's Teams fields).
- Works offline from the last download (the popup says so).
- Follows the Omarchy theme. English and French (Omarchy language, else the
  system locale).

## Install

```bash
omarchy plugin add https://github.com/snouhaud/omarchy-agenda.git --enable
```

Omarchy asks where to put the widget (default: `centerBegin`, just left of the
clock). Move it later with
`omarchy bar move io.github.snouhaud.agenda --section <section>`.

Requires only `python3` (standard library) and `xdg-open`, both present on
Omarchy.

## Get your calendar's ICS link

**Outlook / Microsoft 365**: Outlook on the web → Settings → Calendar →
Shared calendars → *Publish a calendar* → choose your calendar and
"Can view all details" → Publish → copy the **ICS** link.
Your organisation may have disabled publishing.

**Google Calendar**: Settings → your calendar → *Integrate calendar* →
"Secret address in iCal format".

**iCloud**: Calendar → share icon next to the calendar → *Public Calendar*.

> Anyone who has this link can read your calendar. Keep it private.

Then put it in the widget's entry in `~/.config/omarchy/shell.json`:

```json
{ "id": "io.github.snouhaud.agenda", "icsUrl": "https://outlook.office365.com/owa/calendar/…/calendar.ics" }
```

The shell reloads `shell.json` on save.

## Settings

| Key                 | Default | Meaning                                                    |
|---------------------|---------|------------------------------------------------------------|
| `icsUrl`            | `""`    | The ICS link (`https://` or `webcal://`)                   |
| `refreshMinutes`    | `5`     | How often the feed is downloaded                           |
| `daysAhead`         | `7`     | Days shown in the popup                                    |
| `showNextInBar`     | `true`  | Show the next meeting in the bar (else only an icon)       |
| `barLookaheadHours` | `12`    | Show it only when it starts within this many hours         |
| `maxTitleChars`     | `28`    | Title length in the bar                                    |
| `alertMinutes`      | `5`     | Alert color this many minutes before a meeting (0 = never) |
| `hideFree`          | `false` | Hide events marked as free                                 |
| `hideCancelled`     | `true`  | Hide cancelled events                                      |

## Usage

| Action                | Effect                                    |
|-----------------------|-------------------------------------------|
| Click                 | Open / close the agenda                   |
| Right click           | Refresh now                               |
| Middle click          | Join the meeting shown in the bar         |
| ↑ ↓ in the popup      | Move between events                       |
| Enter or `j`          | Join the selected meeting                 |
| `r`                   | Refresh                                   |
| `o`                   | Open Outlook on the web                   |

From a script or a key binding:

```bash
omarchy-shell io.github.snouhaud.agenda joinNext   # join the meeting starting within the hour
omarchy-shell io.github.snouhaud.agenda next       # "<ISO start>\t<title>" of the next meeting
omarchy-shell io.github.snouhaud.agenda refresh
omarchy-shell io.github.snouhaud.agenda toggle
```

## How it works

`agenda-feed.py` downloads the feed (HTTPS only, 25 s timeout, 30 MB cap),
caches it under `~/.cache/omarchy-agenda/` (mode 600) and prints the events of
the coming days as one JSON line. It uses only the Python standard library
and handles what Outlook publishes:

- Windows time zone names (`Romance Standard Time`, `Paris, Madrid`…),
  resolved from the feed's own `VTIMEZONE` blocks, IANA names otherwise;
- recurring events (`RRULE` daily / weekly / monthly / yearly, `INTERVAL`,
  `COUNT`, `UNTIL`, `BYDAY` with positions, `BYMONTHDAY`, `BYMONTH`,
  `BYSETPOS`), deleted (`EXDATE`) and moved or edited (`RECURRENCE-ID`)
  occurrences;
- all-day events, busy status (free / tentative / out of office), cancelled
  events.

The QML side never runs a shell: the helper gets its arguments as argv, its
output is validated and bounded, every text is displayed as plain text, and
only `https://` links to known meeting hosts are passed to `xdg-open`.

## Tests

```bash
python3 -I tests/test_feed.py
```

## Uninstall

```bash
omarchy plugin remove io.github.snouhaud.agenda
rm -rf ~/.cache/omarchy-agenda
```

## License

MIT
