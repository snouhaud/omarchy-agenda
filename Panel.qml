import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Bar widget: the next meeting ("14:00 Point projet", "Point projet in 5 min")
// and, on click, the agenda of the coming days with join buttons.
Panel {
  id: root
  moduleName: "io.github.snouhaud.agenda"
  ipcTarget: "io.github.snouhaud.agenda"
  manageIpc: false

  readonly property Item panelFlick: panel.loadedContent ? panel.loadedContent.panelFlick : null

  property bool cursorActive: false
  property int cursorPos: 0
  // The settings screen replaces the agenda while true.
  property bool settingsMode: false

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property var formatLocale: Qt.locale(Commons.I18n.formatLocale)

  readonly property bool showNextInBar: agenda.setting("showNextInBar", true) !== false
  readonly property int barLookaheadHours: agenda.intSetting("barLookaheadHours", 12, 1, 48)
  readonly property int maxTitleChars: agenda.intSetting("maxTitleChars", 28, 8, 80)
  readonly property int alertMinutes: agenda.intSetting("alertMinutes", 5, 0, 60)

  // Nerd Font (Material Design) glyphs.
  readonly property string glyphCalendar: String.fromCodePoint(0xF00ED)    // calendar
  readonly property string glyphCalendarClock: String.fromCodePoint(0xF00F0) // calendar-clock
  readonly property string glyphVideo: String.fromCodePoint(0xF0567)       // video
  readonly property string glyphRefresh: String.fromCodePoint(0xF0450)     // refresh
  readonly property string glyphWeb: String.fromCodePoint(0xF03CC)         // open-in-new
  readonly property string glyphAlert: String.fromCodePoint(0xF002A)       // alert-outline
  readonly property string glyphSettings: String.fromCodePoint(0xF0493)    // cog

  Strings { id: strings; directory: Qt.resolvedUrl("i18n") }
  readonly property var catalog: strings
  readonly property var service: agenda

  Service {
    id: agenda
    settings: root.settings
  }

  // ---------------------------------------------------------------- bar text

  readonly property var barEvent: showNextInBar && agenda.configured ? agenda.nextEvent(barLookaheadHours, 15) : null
  readonly property real minutesToBarEvent: barEvent ? (barEvent.start - agenda.now) / 60000 : 0
  readonly property bool barAlert: barEvent !== null && alertMinutes > 0 && minutesToBarEvent > 0 && minutesToBarEvent <= alertMinutes
  readonly property bool hasProblem: agenda.lastError !== "" || (agenda.loaded && !agenda.configured)

  function shortTitle(title) {
    var t = String(title || "")
    return t.length > maxTitleChars ? t.substring(0, maxTitleChars - 1).trim() + "…" : t
  }

  function timeText(ms) {
    return new Date(ms).toLocaleTimeString(formatLocale, "HH:mm")
  }

  readonly property string barLabel: {
    var e = barEvent
    if (!e) return ""
    var title = shortTitle(e.title)
    if (e.start <= agenda.now) return strings.t("bar.now").arg(title).arg(timeText(e.end))
    var minutes = Math.ceil(minutesToBarEvent)
    if (minutes <= 60) return strings.tn("bar.in", minutes).arg(Commons.I18n.formatNumber(minutes)).arg(title)
    var sameDay = new Date(e.start).toDateString() === new Date(agenda.now).toDateString()
    var when = sameDay ? timeText(e.start)
      : new Date(e.start).toLocaleString(formatLocale, "ddd HH:mm")
    return strings.t("bar.at").arg(when).arg(title)
  }

  // ---------------------------------------------------------------- agenda days

  function dayStart(ms) {
    var d = new Date(ms)
    d.setHours(0, 0, 0, 0)
    return d.getTime()
  }

  function isoDate(ms) {
    var d = new Date(ms)
    function pad(n) { return n < 10 ? "0" + n : String(n) }
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
  }

  function addDays(ms, n) {
    var d = new Date(ms)
    d.setDate(d.getDate() + n)
    return d.getTime()
  }

  // [{ start, label, events: [...] }] for today (always) and each later day
  // that has something.
  readonly property var days: {
    var today = dayStart(agenda.now)
    var out = []
    for (var i = 0; i < agenda.daysAhead; i++) {
      var start = addDays(today, i)
      var end = addDays(today, i + 1)
      var iso = isoDate(start)
      var list = []
      for (var k = 0; k < agenda.visibleEvents.length; k++) {
        var e = agenda.visibleEvents[k]
        var inDay = e.allDay ? (e.startDate <= iso && iso < e.endDate) : (e.start < end && e.end > start)
        if (inDay) list.push(e)
      }
      list.sort(function(a, b) {
        if (a.allDay !== b.allDay) return a.allDay ? -1 : 1
        return a.start - b.start || a.end - b.end
      })
      if (i === 0 || list.length > 0) out.push({ start: start, offset: i, events: list })
    }
    return out
  }

  readonly property var flatEvents: {
    var out = []
    for (var i = 0; i < days.length; i++)
      for (var k = 0; k < days[i].events.length; k++) out.push(days[i].events[k])
    return out
  }

  readonly property int todayCount: {
    var n = 0
    var list = days.length > 0 && days[0].offset === 0 ? days[0].events : []
    for (var i = 0; i < list.length; i++) if (!list[i].cancelled) n++
    return n
  }

  function dayTitle(day) {
    var date = new Date(day.start)
    var name = date.toLocaleDateString(formatLocale, "dddd d MMMM")
    if (day.offset === 0) return strings.t("today") + " · " + name
    if (day.offset === 1) return strings.t("tomorrow") + " · " + name
    return name.charAt(0).toUpperCase() + name.substring(1)
  }

  function flatIndex(dayIndex, eventIndex) {
    var n = 0
    for (var i = 0; i < dayIndex; i++) n += days[i].events.length
    return n + eventIndex
  }

  function eventState(e) {
    if (e.allDay) return "allDay"
    if (e.end <= agenda.now) return "ended"
    if (e.start <= agenda.now) return "now"
    return "upcoming"
  }

  function eventSubtitle(e) {
    var parts = []
    var state = eventState(e)
    if (e.cancelled) parts.push(strings.t("cancelled"))
    else if (state === "now") parts.push(strings.t("now") + " · " + strings.t("until").arg(timeText(e.end)))
    else if (state === "ended") parts.push(strings.t("ended"))
    if (e.busy === "TENTATIVE") parts.push(strings.t("tentative"))
    else if (e.busy === "FREE") parts.push(strings.t("free"))
    else if (e.busy === "OOF") parts.push(strings.t("outOfOffice"))
    // Drop meeting URLs and the generic Teams label; the join button covers them.
    var place = e.location.replace(/https?:\/\/\S+/g, "").replace(/(Réunion Microsoft Teams|Microsoft Teams Meeting|Microsoft Teams)/gi, "")
    place = place.replace(/\s*[;,]\s*([;,]\s*)*/g, ", ").replace(/^[\s,;·-]+|[\s,;·-]+$/g, "")
    if (place !== "") parts.push(place)
    return parts.join(" · ")
  }

  function errorText() {
    var code = agenda.lastError
    if (code === "") return ""
    var msg = strings.t("error." + code, strings.t("error.generic"))
    return agenda.lastErrorDetail !== "" ? msg + " — " + agenda.lastErrorDetail : msg
  }

  function heroDetail() {
    if (!agenda.configured) return ""
    if (agenda.fetchedAt <= 0) return ""
    var when = new Date(agenda.fetchedAt)
    var sameDay = when.toDateString() === new Date(agenda.now).toDateString()
    var text = sameDay ? when.toLocaleTimeString(formatLocale, "HH:mm") : when.toLocaleString(formatLocale, "d MMM HH:mm")
    if (agenda.stale) return strings.t("hero.stale").arg(text).arg(agenda.staleReason)
    return strings.t("hero.updated").arg(text)
  }

  function heroMeta() {
    if (!agenda.loaded) return strings.t("hero.loading")
    var date = new Date(agenda.now).toLocaleDateString(formatLocale, "dddd d MMMM")
    var count = todayCount > 0
      ? strings.tn("hero.events", todayCount).arg(Commons.I18n.formatNumber(todayCount))
      : strings.t("hero.noEvents")
    return date.charAt(0).toUpperCase() + date.substring(1) + " · " + count
  }

  // ---------------------------------------------------------------- keyboard

  readonly property var cursorEvent: cursorActive && flatEvents.length > 0
    ? flatEvents[Math.max(0, Math.min(cursorPos, flatEvents.length - 1))] : null

  function cursorIs(index) { return cursorActive && cursorPos === index }

  function setCursor(index) {
    if (index < 0 || index >= flatEvents.length) return
    cursorActive = true
    cursorPos = index
  }

  function defaultCursor() {
    // First event that is not over yet, else the first one.
    var pos = 0
    for (var i = 0; i < flatEvents.length; i++) {
      if (flatEvents[i].allDay || flatEvents[i].end > agenda.now) { pos = i; break }
    }
    setCursor(pos)
    scrollCursorIntoView()
  }

  function moveCursor(dy) {
    if (flatEvents.length === 0 || dy === 0) return
    cursorPos = Math.max(0, Math.min(flatEvents.length - 1, cursorPos + dy))
    scrollCursorIntoView()
  }

  function scrollCursorIntoView() {
    if (!panelFlick || !panel.loadedContent) return
    var index = cursorPos
    Qt.callLater(function() {
      var item = panel.loadedContent.rowAt(index)
      if (!item) return
      var margin = Style.space(6)
      var top = item.mapToItem(panelFlick.contentItem, 0, 0).y
      var bottom = top + item.height
      var maxY = Math.max(0, panelFlick.contentHeight - panelFlick.height)
      if (top < panelFlick.contentY + margin) panelFlick.contentY = Math.max(0, top - margin)
      else if (bottom > panelFlick.contentY + panelFlick.height - margin)
        panelFlick.contentY = Math.min(maxY, bottom + margin - panelFlick.height)
    })
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function openSettings() {
    settingsMode = true
    if (panelFlick) panelFlick.contentY = 0
    Qt.callLater(function() { if (panel.loadedContent) panel.loadedContent.focusSettings() })
  }

  function closeSettings() {
    settingsMode = false
    if (panelFlick) panelFlick.contentY = 0
    Qt.callLater(function() { if (panel.loadedContent) panel.loadedContent.forceActiveFocus() })
  }

  onOpenedChanged: if (opened) {
    cursorActive = false
    cursorPos = 0
    agenda.now = Date.now()
    if (panelFlick) panelFlick.contentY = 0
    Qt.callLater(function() {
      if (!panel.loadedContent) return
      if (settingsMode) panel.loadedContent.focusSettings()
      else panel.loadedContent.forceActiveFocus()
    })
  } else {
    settingsMode = false
  }
  onFlatEventsChanged: if (cursorPos >= flatEvents.length) cursorPos = Math.max(0, flatEvents.length - 1)

  ShellIpc {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { agenda.refresh(); return "ok" }
    function openSettings(): void { root.openSettings(); root.open() }
    function next(): string {
      var e = agenda.nextEvent(48, 15)
      return e ? new Date(e.start).toISOString() + "\t" + e.title : ""
    }
    function joinNext(): string {
      var e = agenda.nextEvent(1, 15)
      if (!e || e.joinUrl === "") return "none"
      agenda.join(e)
      return "ok"
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barLabel !== "" ? root.glyphCalendarClock + "  " + root.barLabel : root.glyphCalendar
    foreground: root.hasProblem ? root.urgent
      : root.barAlert ? root.urgent
      : root.barLabel !== "" ? root.barForeground : Qt.darker(root.barForeground, 1.25)
    tooltipText: strings.t("bar.tooltip")
    onPressed: function(b) {
      if (b === Qt.RightButton) agenda.refresh()
      else if (b === Qt.MiddleButton) { if (root.barEvent) agenda.join(root.barEvent) }
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: panel.loadedContent
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(panel.loadedContentHeight, Style.space(620))

    content: PanelKeyCatcher {
      id: keyCatcher
      property alias panelFlick: panelFlick
      implicitHeight: column.implicitHeight
      anchors.fill: parent
      blocked: root.settingsMode

      // With no link yet, the settings open on the link field.
      function focusSettings() {
        if (agenda.configured) settingsPage.forceActiveFocus()
        else settingsPage.focusUrl()
      }

      function rowAt(index) {
        for (var d = 0; d < dayRepeater.count; d++) {
          var group = dayRepeater.itemAt(d)
          if (!group) continue
          var row = group.rowAt(index)
          if (row) return row
        }
        return null
      }

      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.defaultCursor(); return }
        root.moveCursor(dy)
      }
      onActivateRequested: if (root.cursorEvent) agenda.join(root.cursorEvent)
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "r" || t === "R") agenda.refresh()
        else if (t === "o" || t === "O") { agenda.openWeb(); root.close() }
        else if (t === "s" || t === "S" || t === ",") root.openSettings()
        else if (t === "j" || t === "J") {
          var e = root.cursorEvent || root.barEvent
          if (e) agenda.join(e)
        }
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          PanelHero {
            id: hero
            width: parent.width
            visible: !root.settingsMode
            title: agenda.calendarName !== "" && agenda.calendarName !== "Calendrier" && agenda.calendarName !== "Calendar"
              ? strings.t("title") + " · " + agenda.calendarName : strings.t("title")
            meta: root.heroMeta()
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconComponent: Component {
              Text {
                textFormat: Text.PlainText
                text: root.glyphCalendar
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
              }
            }
            trailingControl: Component {
              Row {
                spacing: Style.space(2)
                PanelActionButton {
                  iconText: root.glyphWeb
                  tooltipText: strings.t("openWeb")
                  foreground: hero.foreground
                  fontFamily: hero.fontFamily
                  onClicked: { agenda.openWeb(); root.close() }
                }
                PanelActionButton {
                  iconText: root.glyphSettings
                  tooltipText: strings.t("settings.open")
                  foreground: hero.foreground
                  fontFamily: hero.fontFamily
                  onClicked: root.openSettings()
                }
                PanelActionButton {
                  iconText: root.glyphRefresh
                  tooltipText: strings.t("refresh")
                  foreground: hero.foreground
                  fontFamily: hero.fontFamily
                  enabled: !agenda.refreshing && agenda.configured
                  onClicked: agenda.refresh()
                }
              }
            }
          }

          // The agenda; the settings screen takes its place.
          Column {
            id: listPart
            width: parent.width
            spacing: Style.space(12)
            visible: !root.settingsMode

            // Not configured yet.
            CursorSurface {
              visible: agenda.loaded && !agenda.configured
              width: parent.width
              foreground: root.urgent
              bordered: true
              implicitHeight: setupLayout.implicitHeight + Style.spacing.rowPaddingX

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.openSettings()
            }

              RowLayout {
                id: setupLayout
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(8)

                Text {
                  textFormat: Text.PlainText
                  text: root.glyphAlert
                  color: root.urgent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.heading
                  Layout.alignment: Qt.AlignVCenter
                }
                ColumnLayout {
                  Layout.fillWidth: true
                  spacing: Style.space(1)
                  Text {
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    text: strings.t("alert.noUrl")
                    color: root.urgent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    wrapMode: Text.WordWrap
                  }
                  Text {
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    text: strings.t("alert.noUrlHelp")
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }
              }
            }

            Text {
              textFormat: Text.PlainText
              visible: text !== ""
              width: parent.width
              text: root.errorText()
              color: root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }

            Repeater {
              id: dayRepeater
              model: agenda.configured && agenda.lastError === "" || agenda.events.length > 0 ? root.days : []

              DayGroup {
                required property var modelData
                required property int index
                width: column.width
                day: modelData
                dayIndex: index
              }
            }

            Text {
              textFormat: Text.PlainText
              visible: agenda.configured && agenda.loaded && root.flatEvents.length === 0 && agenda.lastError === ""
              width: parent.width
              text: strings.t("nothingAhead")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            Text {
              textFormat: Text.PlainText
              visible: text !== ""
              width: parent.width
              text: root.heroDetail()
              color: agenda.stale ? root.urgent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignRight
              elide: Text.ElideRight
            }
          }

          SettingsPage {
            id: settingsPage
            width: parent.width
            visible: root.settingsMode
            // Through root: inside this element, "agenda" would name its own property.
            agenda: root.service
            strings: root.catalog
            foreground: root.foreground
            dim: root.dim
            urgent: root.urgent
            fontFamily: root.fontFamily
            onBack: root.closeSettings()
          }
        }
      }
    }
  }

  component DayGroup: Column {
    id: group
    property var day: null
    property int dayIndex: 0
    spacing: Style.space(4)

    function rowAt(index) {
      for (var i = 0; i < rows.count; i++) {
        var row = rows.itemAt(i)
        if (row && row.flat === index) return row
      }
      return null
    }

    PanelSectionHeader {
      text: group.day ? root.dayTitle(group.day) : ""
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    Text {
      textFormat: Text.PlainText
      visible: group.day !== null && group.day.offset === 0
        && !group.day.events.some(function(e) { return e.allDay || e.end > agenda.now })
      width: parent.width
      leftPadding: Style.space(10)
      text: strings.t("nothingToday")
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }

    Repeater {
      id: rows
      model: group.day ? group.day.events : []
      EventRow {
        required property var modelData
        required property int index
        width: group.width
        event: modelData
        flat: root.flatIndex(group.dayIndex, index)
      }
    }
  }

  component EventRow: CursorSurface {
    id: row
    property var event: null
    property int flat: 0
    readonly property string phase: event ? root.eventState(event) : ""
    readonly property bool past: phase === "ended" || (event !== null && event.cancelled)
    readonly property bool canJoin: event !== null && event.joinUrl !== "" && phase !== "ended" && !event.cancelled
    readonly property string subtitle: event ? root.eventSubtitle(event) : ""

    hasCursor: root.cursorIs(flat)
    current: phase === "now"
    foreground: root.foreground
    implicitHeight: rowLayout.implicitHeight + Style.spacing.rowPaddingX
    opacity: past ? 0.5 : 1.0

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: row.canJoin ? Qt.PointingHandCursor : Qt.ArrowCursor
      onEntered: root.setCursor(row.flat)
      onClicked: if (row.canJoin) agenda.join(row.event)
    }

    RowLayout {
      id: rowLayout
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(4)
      spacing: Style.space(10)

      ColumnLayout {
        Layout.preferredWidth: Style.space(44)
        Layout.alignment: Qt.AlignTop
        spacing: Style.space(1)
        Text {
          textFormat: Text.PlainText
          text: !row.event ? "" : row.event.allDay ? strings.t("allDay") : root.timeText(row.event.start)
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: row.event && row.event.allDay ? Style.font.caption : Style.font.body
        }
        Text {
          textFormat: Text.PlainText
          visible: row.event !== null && !row.event.allDay
          text: row.event ? root.timeText(row.event.end) : ""
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(1)
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: row.event ? row.event.title : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.strikeout: row.event !== null && row.event.cancelled
          font.italic: row.event !== null && row.event.busy === "TENTATIVE"
          elide: Text.ElideRight
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          visible: text !== ""
          text: row.subtitle
          color: row.phase === "now" ? root.foreground : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      PanelActionButton {
        visible: row.canJoin
        iconText: root.glyphVideo
        tooltipText: strings.t("join")
        foreground: root.foreground
        fontFamily: root.fontFamily
        hasCursor: row.hasCursor
        Layout.alignment: Qt.AlignVCenter
        onHovered: function(on) { if (on) root.setCursor(row.flat) }
        onClicked: agenda.join(row.event)
      }
    }
  }
}
