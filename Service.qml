import QtQuick
import Quickshell
import Quickshell.Io

// Runs agenda-feed.py (argv only, never a shell string) and keeps the
// validated, bounded list of events. `now` ticks every 30 s so labels such
// as "in 5 min" stay current between downloads.
Item {
  id: root

  property var settings: ({})

  property bool loaded: false
  property var events: []
  property string calendarName: ""
  property bool stale: false
  property string staleReason: ""
  property double fetchedAt: 0
  property string lastError: ""
  property string lastErrorDetail: ""
  property double now: Date.now()

  readonly property bool refreshing: feedProcess.running
  readonly property string helperPath: decodeURIComponent(String(Qt.resolvedUrl("agenda-feed.py")).replace(/^file:\/\//, ""))
  readonly property string icsUrl: String(setting("icsUrl", "")).trim().substring(0, 2048)
  readonly property bool configured: icsUrl !== ""
  readonly property int refreshMinutes: intSetting("refreshMinutes", 5, 1, 120)
  readonly property int daysAhead: intSetting("daysAhead", 7, 1, 31)
  readonly property bool hideFree: setting("hideFree", false) === true
  readonly property bool hideCancelled: setting("hideCancelled", true) !== false

  // Events after the user's filters.
  readonly property var visibleEvents: {
    var out = []
    for (var i = 0; i < events.length; i++) {
      var e = events[i]
      if (hideFree && e.busy === "FREE") continue
      if (hideCancelled && e.cancelled) continue
      out.push(e)
    }
    return out
  }

  // The meeting the bar talks about: one starting within a few minutes beats
  // the one in progress, which beats the next one later on.
  function nextEvent(lookaheadHours, soonMinutes) {
    var ongoing = null
    var upcoming = null
    var horizon = now + lookaheadHours * 3600000
    for (var i = 0; i < visibleEvents.length; i++) {
      var e = visibleEvents[i]
      if (e.allDay || e.cancelled) continue
      if (e.end <= now) continue
      if (e.start <= now) { if (!ongoing) ongoing = e; continue }
      if (e.start <= horizon && !upcoming) upcoming = e
    }
    if (upcoming && ongoing && upcoming.start - now > soonMinutes * 60000) return ongoing
    return upcoming || ongoing
  }

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function intSetting(name, fallback, min, max) {
    var n = parseInt(String(setting(name, fallback)), 10)
    if (!isFinite(n)) n = fallback
    return Math.max(min, Math.min(max, n))
  }

  function clip(value, limit) {
    return String(value === undefined || value === null ? "" : value).replace(/[\u0000-\u001f\u007f]+/g, " ").substring(0, limit)
  }

  // Only well-known meeting hosts, over https, ever reach xdg-open.
  function safeJoinUrl(url) {
    var s = String(url || "")
    if (s.length > 2000) return ""
    if (!/^https:\/\/(teams\.microsoft\.com|teams\.live\.com|([a-z0-9-]+\.)?zoom\.us|meet\.google\.com|[a-z0-9-]+\.webex\.com|whereby\.com)\//i.test(s)) return ""
    if (/[\s"'<>`\\]/.test(s)) return ""
    return s
  }

  function setError(code, detail) {
    lastError = String(code || "")
    lastErrorDetail = clip(detail, 200).trim()
  }

  function refresh() {
    now = Date.now()
    if (!configured) { loaded = true; events = []; setError("", ""); return }
    if (feedProcess.running) return
    feedProcess.command = ["python3", "-I", helperPath, icsUrl, String(daysAhead)]
    feedProcess.running = true
  }

  function apply(raw) {
    var obj = null
    try {
      var text = String(raw || "").trim()
      if (text.length > 0 && text.length < 2000000) obj = JSON.parse(text.split("\n").pop())
    } catch (e) {
      obj = null
    }
    loaded = true
    if (!obj || typeof obj !== "object") { setError("helperFailed", ""); return }
    if (obj.ok !== true) { setError(obj.error, obj.detail); return }

    var list = Array.isArray(obj.events) ? obj.events.slice(0, 400) : []
    var clean = []
    for (var i = 0; i < list.length; i++) {
      var e = list[i]
      if (!e) continue
      var start = Number(e.start) * 1000
      var end = Number(e.end) * 1000
      if (!isFinite(start) || !isFinite(end) || end < start) continue
      var busy = ["BUSY", "FREE", "TENTATIVE", "OOF", "WORKINGELSEWHERE"].indexOf(e.busy) !== -1 ? e.busy : "BUSY"
      clean.push({
        title: clip(e.title, 200),
        location: clip(e.location, 200),
        start: start,
        end: end,
        allDay: e.allDay === true,
        startDate: clip(e.startDate, 10),
        endDate: clip(e.endDate, 10),
        cancelled: e.cancelled === true,
        busy: busy,
        joinUrl: safeJoinUrl(e.joinUrl)
      })
    }
    events = clean
    calendarName = clip(obj.calendarName, 80)
    stale = obj.stale === true
    staleReason = clip(obj.staleReason, 200)
    var fetched = Number(obj.fetchedAt)
    fetchedAt = isFinite(fetched) ? fetched * 1000 : 0
    setError("", "")
  }

  function join(event) {
    var url = event ? safeJoinUrl(event.joinUrl) : ""
    if (url !== "") Quickshell.execDetached(["xdg-open", url])
  }

  function openWeb() {
    Quickshell.execDetached(["xdg-open", "https://outlook.office.com/calendar/view/week"])
  }

  onIcsUrlChanged: Qt.callLater(refresh)
  onDaysAheadChanged: Qt.callLater(refresh)

  Timer {
    interval: root.refreshMinutes * 60000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    interval: 30000
    repeat: true
    running: true
    onTriggered: root.now = Date.now()
  }

  Process {
    id: feedProcess
    running: false
    command: []
    stdout: StdioCollector { id: feedOut; waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode === 0) root.apply(feedOut.text)
      else { root.loaded = true; root.setError("helperFailed", "exit " + exitCode) }
    }
  }
}
