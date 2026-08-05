import QtQuick

// Critical alarm banner (widgets/alarm_bar.py): full-width flashing red bar
// along the bottom; impossible to miss, unlike the calm tell-tales.
Rectangle {
    id: bar
    readonly property var alarms: sensors.alarms
    readonly property bool active: alarms.length > 0

    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    height: 60

    property bool flashOn: true
    Timer {
        interval: 250; running: bar.active; repeat: true
        onTriggered: bar.flashOn = !bar.flashOn
        onRunningChanged: if (!running) bar.flashOn = true
    }

    color: Qt.rgba(Theme.alarmBg.r, Theme.alarmBg.g, Theme.alarmBg.b,
                   active ? (flashOn ? 1.0 : 0.16) : 0)

    Text {
        anchors.centerIn: parent
        text: bar.alarms.join("      ")
        font.family: Theme.fontMono
        font.pixelSize: 34
        font.bold: true
        color: Qt.rgba(1, 1, 1, bar.active ? (bar.flashOn ? 1.0 : 0.55) : 0)
    }
}
