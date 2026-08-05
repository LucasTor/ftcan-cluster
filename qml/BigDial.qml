import QtQuick
import Cluster 1.0

// RPM dial for the dense "detail" layout (widgets/big_dial.py, GhostDash
// style). The comet-trail ring band is the Python RingItem (vertex-coloured
// strip); face, needle, hub, rim dots, numbers and gear are QML on top.
// The RPM readout + shift LEDs are drawn by the layout, not here.
Item {
    id: dial
    property real rpm: 0          // live value from the layout
    property string gearLabel: "N"
    // geometry from the shared dial_spec (via the bridge), same numbers the
    // Kivy dial and the Python RingItem use
    readonly property var spec: sensors.dial
    readonly property real maxValue: spec.maxRpm
    readonly property real start: spec.start      // 0 at ~6:40 (0 = top, +ve cw)
    readonly property real sweep: spec.sweep
    readonly property real hubR: spec.hubR
    readonly property real outer: spec.outer

    width: 600
    height: 600

    // startup self-test sweep, then live (shared intro spec via the bridge)
    readonly property var intro: sensors.intro
    property real introRpm: 0
    property bool introDone: false
    SequentialAnimation {
        running: true
        PauseAnimation { duration: dial.intro.pause }
        NumberAnimation { target: dial; property: "introRpm"; to: dial.maxValue; duration: dial.intro.sweep; easing.type: Easing.OutCubic }
        PauseAnimation { duration: dial.intro.dialHold }
        NumberAnimation { target: dial; property: "introRpm"; to: 0; duration: dial.intro.back; easing.type: Easing.OutCubic }
        ScriptAction { script: dial.introDone = true }
    }

    // display-smoothed RPM shared by the ring trail and the needle
    // (stands in for the Kivy 8/s exponential approach)
    readonly property real targetRpm: introDone ? rpm : introRpm
    property real disp: targetRpm
    Behavior on disp { NumberAnimation { duration: 150 } }

    // black face disc (extends 12 px past the ring)
    Rectangle {
        anchors.centerIn: parent
        width: 2 * (dial.outer + 12)
        height: width
        radius: width / 2
        color: "black"
    }

    RingItem {
        anchors.fill: parent
        rpm: dial.disp
        dim: Theme.dim
    }

    // black needle with a white edge, pointing at the current RPM
    Item {
        anchors.fill: parent
        rotation: dial.start + (dial.disp / dial.maxValue) * dial.sweep
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: dial.height / 2 - (dial.outer - 2)
            width: 8
            height: (dial.outer - 2) - (dial.hubR - 4)
            radius: 4
            color: Theme.d(Qt.rgba(1, 1, 1, 0.92))
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: dial.height / 2 - (dial.outer - 2)
            width: 4.5
            height: (dial.outer - 2) - (dial.hubR - 4)
            radius: 2.25
            color: Qt.rgba(0.04, 0.04, 0.05, 1.0)
        }
    }

    // big black hub (holds the gear)
    Rectangle {
        anchors.centerIn: parent
        width: 2 * dial.hubR
        height: width
        radius: dial.hubR
        color: "black"
    }

    // rim dots just outside the ring
    Repeater {
        model: 17    // (ticks-1)*2 + 1
        delegate: Rectangle {
            readonly property real th: (dial.start + (index / 16) * dial.sweep) * Math.PI / 180
            x: dial.width / 2 + (dial.outer + 15) * Math.sin(th) - 3
            y: dial.height / 2 - (dial.outer + 15) * Math.cos(th) - 3
            width: 6; height: 6; radius: 3
            color: Theme.d(Qt.rgba(0.36, 0.40, 0.47, 1.0))
        }
    }

    // big bold numbers on the ring band
    Repeater {
        model: 9
        delegate: Text {
            readonly property real th: (dial.start + (index / 8) * dial.sweep) * Math.PI / 180
            x: dial.width / 2 + dial.spec.numR * Math.sin(th) - width / 2
            y: dial.height / 2 - dial.spec.numR * Math.cos(th) - height / 2
            text: index
            font.family: Theme.fontBold
            font.bold: true
            font.pixelSize: 80
            style: Text.Outline
            styleColor: Theme.d("white")
            color: Qt.rgba(0.05, 0.07, 0.10, 1.0)
        }
    }

    // gear in the hub (lifted ~0.14em — Compagnon's line box is bottom-heavy)
    Text {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -Math.round(0.143 * 150) / 2
        text: dial.gearLabel
        font.family: Theme.fontBold
        font.bold: true
        font.pixelSize: 150
        color: Theme.d(Qt.rgba(0.98, 0.99, 1.0, 1.0))
    }
}
