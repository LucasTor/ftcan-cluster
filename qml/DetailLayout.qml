import QtQuick

// Dense view (widgets/layouts.py DetailLayout): left RPM dial with the gear in
// the hub, big RPM readout + 20 shift LEDs in the bottom band, and a 4x3 grid
// of stat tiles on the right (GhostDash style; one slot left empty).
Item {
    id: layout
    anchors.fill: parent

    readonly property real shiftRpm: 6000
    readonly property real ledStart: 3500
    readonly property real boost: Math.max(0, sensors.map)

    BigDial {
        x: 40; y: 60
        rpm: sensors.rpm
        gearLabel: sensors.gear_label
    }

    // big RPM readout + sub-label, centred at (632, 186) in design space
    Text {
        x: 632 - 390; y: 720 - 186 - 75
        width: 780; height: 150
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        text: sensors.live ? Math.round(sensors.rpm).toString() : "0"
        font.family: Theme.fontBold
        font.bold: true
        font.pixelSize: 124
        color: Theme.d(Qt.rgba(0.97, 0.98, 1.0, 1.0))
    }
    Text {
        x: 632 - 390; y: 720 - 90 - 24
        width: 780; height: 24
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        text: "RPM"
        font.family: Theme.fontMono
        font.pixelSize: 20
        color: Theme.labelAccent
    }

    // shift LEDs: green -> amber -> red filling toward the shift point,
    // all flashing red at/over it
    property bool ledFlashOn: true
    Timer {
        interval: 133; repeat: true
        running: sensors.rpm >= layout.shiftRpm
        onTriggered: layout.ledFlashOn = !layout.ledFlashOn
        onRunningChanged: if (!running) layout.ledFlashOn = true
    }
    readonly property int ledsLit: Math.round(Math.max(0, Math.min(1,
        (sensors.rpm - ledStart) / (shiftRpm - ledStart))) * 20)
    Row {
        x: 632 - (19 * 30) / 2 - 9
        y: 720 - 58 - 9
        spacing: 30 - 18
        Repeater {
            model: 20
            delegate: Rectangle {
                readonly property real f: index / 19
                width: 18; height: 18; radius: 9
                color: {
                    if (sensors.rpm >= layout.shiftRpm)
                        return layout.ledFlashOn ? Qt.rgba(1.0, 0.20, 0.12, 1.0)
                                                 : Qt.rgba(1, 1, 1, 0.10)
                    if (index >= layout.ledsLit)
                        return Qt.rgba(1, 1, 1, 0.10)
                    return f < 0.45 ? Qt.rgba(0.20, 0.85, 0.30, 1.0)
                         : f < 0.75 ? Qt.rgba(1.0, 0.72, 0.10, 1.0)
                         : Qt.rgba(1.0, 0.20, 0.12, 1.0)
                }
            }
        }
    }

    // 4x3 stat-tile grid (x = 700 + col*298, top rows at y 90/285/480)
    StatTile { x: 700; y: 90; label: "BOOST"; unit: "BAR"; vmin: 0; vmax: 2
        decimals: 2; warnFn: v => v > 1.32; warnColor: Theme.ttRed
        value: layout.boost }
    StatTile { x: 998; y: 90; label: "FUEL LEVEL"; unit: "%"; vmin: 0; vmax: 100
        decimals: 0; value: sensors.fuel_level }
    StatTile { x: 1296; y: 90; label: "ENGINE TEMP"; unit: "°C"; vmin: 0; vmax: 120
        decimals: 0; warnFn: v => v > 104; warnColor: Theme.ttRed
        value: sensors.engine_temp }
    StatTile { x: 1594; y: 90; label: "INTAKE TEMP"; unit: "°C"; vmin: 0; vmax: 110
        decimals: 0; warnFn: v => v > 58; warnColor: Theme.ttAmber
        value: sensors.air_temp }

    StatTile { x: 700; y: 285; label: "BATTERY"; unit: "V"; vmin: 8; vmax: 16
        decimals: 1; warnFn: v => v < 11.5; warnColor: Theme.ttRed
        value: sensors.battery }
    StatTile { x: 998; y: 285; label: "FUEL PRESS"; unit: "BAR"; vmin: 0; vmax: 6
        decimals: 1; value: sensors.fuel_pressure_bar }
    StatTile { x: 1296; y: 285; label: "OIL PRESS"; unit: "BAR"; vmin: 0; vmax: 10
        decimals: 1; value: sensors.oil_pressure_bar }
    StatTile { x: 1594; y: 285; label: "ETHANOL"; unit: "%"; vmin: 0; vmax: 100
        decimals: 0; prefix: "E"; value: sensors.ethanol }

    // slot at (700, 480) intentionally empty (gear lives in the dial hub)
    StatTile { x: 998; y: 480; label: "TPS"; unit: "%"; vmin: 0; vmax: 100
        decimals: 0; value: sensors.tps }
    StatTile { x: 1296; y: 480; label: "MAP"; unit: "BAR"; vmin: 0; vmax: 3
        decimals: 2; value: layout.boost }
    StatTile { x: 1594; y: 480; label: "LAMBDA"; unit: "λ"; vmin: 0.7; vmax: 1.3
        decimals: 2; warnFn: v => v > 1.05; warnColor: Theme.ttRed
        value: sensors.lambda_afr }
}
