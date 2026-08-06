import QtQuick

// Session-peaks card (fills the detail grid's formerly empty slot): highest
// RPM / boost / speed / EGT since power-on, from decisions.PeakTracker via
// the bridge. Static rows with per-value bindings — not a JS-array Repeater
// model (see the CenterInfo micro-grid rule).
Rectangle {
    width: 282
    height: 180
    color: "black"
    radius: 6
    border.color: Theme.d(Qt.rgba(0.32, 0.60, 0.72, 0.30))
    border.width: 1.3

    component PeakRow: Item {
        property string label: ""
        property string value: ""
        x: 16; width: 250; height: 31
        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: label
            font.family: Theme.fontMono
            font.pixelSize: 16
            color: Theme.labelAccent
        }
        Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: sensors.live ? value : "—"
            font.family: Theme.fontBold
            font.bold: true
            font.pixelSize: 24
            color: Theme.d(Qt.rgba(0.97, 0.98, 1.0, 1.0))
        }
    }

    Text {   // label (top; matching the StatTile header)
        anchors.horizontalCenter: parent.horizontalCenter
        y: 21 - height / 2
        text: "PEAKS"
        font.family: Theme.fontMain; font.weight: Theme.weightMain
        font.pixelSize: 19
        color: Theme.d(Qt.rgba(0.80, 0.84, 0.88, 0.92))
    }

    PeakRow { y: 42;  label: "RPM";   value: Math.round(sensors.peak_rpm).toString() }
    PeakRow { y: 74;  label: "BOOST"; value: sensors.peak_boost.toFixed(2) + " BAR" }
    PeakRow { y: 106; label: "SPEED"; value: Math.round(sensors.peak_speed) + " KM/H" }
    PeakRow { y: 138; label: "EGT";   value: Math.round(sensors.peak_egt) + " °C" }
}
