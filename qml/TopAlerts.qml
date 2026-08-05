import QtQuick

// Top-of-cluster tell-tale row (widgets/top_alerts.py). Which pills exist and
// which are active is decided Python-side (SensorBridge.pill_model /
// pill_active — including the boot bulb-check chase); this row just renders.
// The 0.4 s blink for blinking pills is presentation, so it lives here.
Item {
    id: alerts
    width: parent ? parent.width : Theme.windowWidth
    height: 40

    property bool blinkOn: true
    Timer {
        interval: 400; running: true; repeat: true
        onTriggered: alerts.blinkOn = !alerts.blinkOn
    }

    // the shared pill spec names colours; resolve them against the theme here
    function ttColor(name) {
        return name === "green" ? Theme.ttGreen
             : name === "blue"  ? Theme.ttBlue
             : name === "amber" ? Theme.ttAmber
             : name === "cyan"  ? Theme.ttCyan
             : Theme.ttRed
    }

    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 0
        spacing: 10
        Repeater {
            model: sensors.pill_model
            delegate: TellTale {
                readonly property var pillState: sensors.pill_active[modelData.key]
                readonly property bool active: pillState !== undefined
                    && pillState !== false && pillState !== 0
                icon: modelData.icon
                onColor: alerts.ttColor(modelData.color)
                litColor: (typeof pillState === "string")
                    ? alerts.ttColor(pillState) : onColor
                lit: active && (!modelData.blinks || alerts.blinkOn || sensors.pill_chase)
            }
        }
    }

    // standalone WiFi tell-tale (top-left): hidden unless connected
    TellTale {
        x: 40
        icon: 0xF05A9
        onColor: Theme.ttBlue
        lit: true
        visible: sensors.wifi
    }
}
