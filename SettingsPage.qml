import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// The widget's settings, inside its popup: the calendar's ICS link and how
// many days the popup shows. Each change is written to shell.json at once
// (Service.saveSetting, through `omarchy-bar set`).
FocusScope {
  id: page

  required property var agenda
  required property var strings
  property color foreground: Commons.Color.foreground
  property color dim: Qt.darker(foreground, 1.55)
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family

  signal back()

  readonly property string glyphBack: String.fromCodePoint(0xF004D)    // arrow-left
  readonly property string glyphShow: String.fromCodePoint(0xF0208)    // eye
  readonly property string glyphHide: String.fromCodePoint(0xF0209)    // eye-off
  readonly property string glyphSave: String.fromCodePoint(0xF012C)    // check
  readonly property string glyphClear: String.fromCodePoint(0xF0156)   // close

  property bool revealUrl: false
  property string urlError: ""

  readonly property var dayChoices: {
    var list = [1, 3, 5, 7, 14]
    var current = agenda.daysAhead
    if (list.indexOf(current) === -1) { list.push(current); list.sort(function(a, b) { return a - b }) }
    return list
  }

  // Same rule as agenda-feed.py: https:// (webcal:// is turned into it).
  function checkUrl(text) {
    var t = String(text || "").trim()
    if (t === "") return ""
    if (!/^(https|webcal):\/\/\S{4,2040}$/i.test(t)) return strings.t("settings.badUrl")
    return ""
  }

  function saveUrl() {
    var t = urlField.text.trim()
    urlError = checkUrl(t)
    if (urlError !== "") return false
    if (t !== agenda.icsUrl) agenda.saveSetting("icsUrl", t)
    return true
  }

  function focusUrl() { urlField.forceActiveFocus() }

  implicitHeight: column.implicitHeight
  Keys.onEscapePressed: page.back()
  onVisibleChanged: if (!visible) { revealUrl = false; urlError = ""; urlField.text = agenda.icsUrl }

  Column {
    id: column
    width: page.width
    spacing: Style.space(12)

    RowLayout {
      width: parent.width
      spacing: Style.space(6)
      PanelActionButton {
        iconText: page.glyphBack
        tooltipText: strings.t("settings.back")
        foreground: page.foreground
        fontFamily: page.fontFamily
        onClicked: page.back()
      }
      Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        text: strings.t("settings.title")
        color: page.foreground
        font.family: page.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
      }
    }

    // -------------------------------------------------- calendar link

    PanelSectionHeader {
      text: strings.t("settings.url")
      foreground: page.foreground
      fontFamily: page.fontFamily
    }

    RowLayout {
      width: parent.width
      spacing: Style.space(4)

      TextField {
        id: urlField
        Layout.fillWidth: true
        foreground: page.foreground
        maximumLength: 2048
        // The link gives read access to the calendar: hidden unless asked.
        password: !page.revealUrl
        text: agenda.icsUrl
        placeholderText: "https://outlook.office365.com/owa/calendar/…/calendar.ics"
        onTextEdited: page.urlError = ""
        Keys.onReturnPressed: if (page.saveUrl()) page.forceActiveFocus()
        Keys.onEnterPressed: if (page.saveUrl()) page.forceActiveFocus()
        Keys.onEscapePressed: { text = agenda.icsUrl; page.urlError = ""; page.forceActiveFocus() }
      }
      PanelActionButton {
        iconText: page.revealUrl ? page.glyphHide : page.glyphShow
        tooltipText: page.revealUrl ? strings.t("settings.hideUrl") : strings.t("settings.showUrl")
        foreground: page.foreground
        fontFamily: page.fontFamily
        onClicked: page.revealUrl = !page.revealUrl
      }
      PanelActionButton {
        iconText: page.glyphSave
        tooltipText: strings.t("settings.saveUrl")
        foreground: page.foreground
        fontFamily: page.fontFamily
        enabled: urlField.text.trim() !== agenda.icsUrl
        onClicked: page.saveUrl()
      }
      PanelActionButton {
        iconText: page.glyphClear
        tooltipText: strings.t("settings.clearUrl")
        foreground: page.foreground
        hoverColor: page.urgent
        fontFamily: page.fontFamily
        enabled: agenda.icsUrl !== ""
        onClicked: { urlField.text = ""; page.saveUrl() }
      }
    }

    Text {
      textFormat: Text.PlainText
      width: parent.width
      visible: page.urlError !== ""
      text: page.urlError
      color: page.urgent
      font.family: page.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Text {
      textFormat: Text.PlainText
      width: parent.width
      text: strings.t("settings.urlHelp")
      color: page.dim
      font.family: page.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    // -------------------------------------------------- days

    PanelSectionHeader {
      text: strings.t("settings.days")
      foreground: page.foreground
      fontFamily: page.fontFamily
    }

    ButtonGroup {
      focusable: true
      foreground: page.foreground
      fontFamily: page.fontFamily
      options: page.dayChoices.map(function(n) {
        return { value: String(n), label: strings.tn("settings.dayCount", n).arg(Commons.I18n.formatNumber(n)) }
      })
      value: String(agenda.daysAhead)
      onChanged: function(v) { agenda.saveSetting("daysAhead", parseInt(v, 10)) }
    }

    // -------------------------------------------------- bar

    PanelSectionHeader {
      text: strings.t("settings.barLength")
      foreground: page.foreground
      fontFamily: page.fontFamily
    }

    NumberField {
      // Typed in, or stepped with the arrows: 4 to 120 characters.
      foreground: page.foreground
      fontFamily: page.fontFamily
      from: 4
      to: 120
      value: agenda.intSetting("maxTitleChars", 28, 4, 120)
      onModified: function(v) { agenda.saveSetting("maxTitleChars", v) }
    }

    Text {
      textFormat: Text.PlainText
      width: parent.width
      visible: agenda.saveError !== ""
      text: strings.t("settings.saveFailed").arg(agenda.saveError)
      color: page.urgent
      font.family: page.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Text {
      textFormat: Text.PlainText
      width: parent.width
      text: strings.t("settings.savedIn")
      color: page.dim
      font.family: page.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }
}
