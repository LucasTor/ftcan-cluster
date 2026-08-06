import QtQuick
import QtQuick.Shapes

// Minimal analog gauge — QML port of widgets/gauge.py. Hairline ticks and a
// thin Azul Boreal needle on a dark disc with a thin progress arc; at the
// shift point the arc and needle flash amber and a red SHIFT! pulses over the
// centre. The needle Behavior replaces the Kivy 60 Hz smoothing timer; the
// startup self-test sweep is a SequentialAnimation timed like the Kivy one
// (sweep at 2.5 s, reset at 3.8 s — the render loop starts at 5 s).
Item {
    id: gauge
    property string title: "SPEED"
    property string subtitle: ""
    property real maxValue: 180
    property int ticks: 10
    property real angleRange: 270
    property real redlineFrom: 0        // 0 = no redline
    property var labelMap: ({})         // dial-number overrides, e.g. {1000: "1"}
    property bool showDigitalValue: true
    property string formatMode: "int"   // "int" | "rpm" (x.xk above 1000)
    property real value: 0
    property bool shift: false

    width: 600
    height: 600

    readonly property real r: width / 2
    readonly property real frac: Math.max(0, Math.min(value, maxValue)) / maxValue
    readonly property real zeroAngle: -(angleRange / 2)   // deg from 12 o'clock

    // live needle position (exponential-ish smoothing, like smooth_update)
    property real smoothFrac: frac
    Behavior on smoothFrac { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }

    // startup sweep: needle+arc only, the digit stays put (update_label=False).
    // Timing comes from the shared intro spec (via the bridge), same numbers
    // the Kivy gauge uses.
    readonly property var intro: sensors.intro
    property real introFrac: 0
    property bool introDone: false
    readonly property real shownFrac: introDone ? smoothFrac : introFrac
    SequentialAnimation {
        running: true
        PauseAnimation { duration: gauge.intro.pause }
        NumberAnimation { target: gauge; property: "introFrac"; to: 1; duration: gauge.intro.sweep; easing.type: Easing.OutCubic }
        PauseAnimation { duration: gauge.intro.gaugeHold }
        NumberAnimation { target: gauge; property: "introFrac"; to: 0; duration: gauge.intro.back; easing.type: Easing.OutCubic }
        ScriptAction { script: gauge.introDone = true }
    }

    function fmtValue(v) {
        if (formatMode === "rpm")
            return v < 1000 ? Math.round(v).toString() : (v / 1000).toFixed(1) + "k"
        return Math.round(v).toString()
    }

    // dark dial face + faint edge ring
    Rectangle {
        anchors.fill: parent
        radius: gauge.r
        color: Theme.gaugeFace
        border.color: Theme.gaugeRing
        border.width: 1
    }

    // red disc wash strobed while shifting (never touches the centre text)
    Rectangle {
        id: flashWash
        anchors.fill: parent
        radius: gauge.r
        color: Theme.gaugeShiftFlash
        opacity: 0
        SequentialAnimation on opacity {
            running: gauge.shift
            loops: Animation.Infinite
            // when shift drops mid-strobe the animation halts wherever it is —
            // clear the wash or it stays stuck on the bright phase
            onRunningChanged: if (!running) flashWash.opacity = 0
            PropertyAction { value: 0.55 }
            PauseAnimation { duration: 60 }
            PropertyAction { value: 0 }
            PauseAnimation { duration: 60 }
        }
    }

    // ticks: bright majors + faint minors at the midpoints
    Repeater {
        model: gauge.ticks * 2 - 1
        delegate: Item {
            anchors.fill: parent
            rotation: gauge.zeroAngle + gauge.angleRange * index / ((gauge.ticks - 1) * 2)
            readonly property bool major: index % 2 === 0
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: gauge.r * 0.10
                width: major ? 3 : 1.5
                height: major ? gauge.r * 0.10 : gauge.r * 0.05
                radius: width / 2
                color: major ? Theme.gaugeTick : Theme.gaugeTickMinor
            }
        }
    }

    // dial numerals, upright on the 0.66R circle
    Repeater {
        model: gauge.ticks
        delegate: Text {
            readonly property int tickValue: Math.round(index / (gauge.ticks - 1) * gauge.maxValue)
            readonly property real a: (gauge.zeroAngle
                + gauge.angleRange * index / (gauge.ticks - 1)) * Math.PI / 180
            x: gauge.r + gauge.r * 0.66 * Math.sin(a) - width / 2
            y: gauge.r - gauge.r * 0.66 * Math.cos(a) - height / 2
            text: gauge.labelMap[tickValue] !== undefined ? gauge.labelMap[tickValue] : tickValue
            font.family: Theme.fontMain
            font.weight: Theme.weightMain
            font.pixelSize: 30
            color: Theme.gaugeNum
        }
    }

    // redline arc
    Shape {
        anchors.fill: parent
        visible: gauge.redlineFrom > 0 && gauge.redlineFrom < gauge.maxValue
        ShapePath {
            strokeWidth: 8
            strokeColor: Theme.gaugeRedline
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: gauge.r; centerY: gauge.r
                radiusX: gauge.r * 0.92; radiusY: gauge.r * 0.92
                startAngle: 90 + (360 - gauge.angleRange) / 2
                    + gauge.angleRange * (gauge.redlineFrom / gauge.maxValue)
                sweepAngle: gauge.angleRange * (1 - gauge.redlineFrom / gauge.maxValue)
            }
        }
    }

    // bold progress arc (fat amber while shifting)
    Shape {
        anchors.fill: parent
        ShapePath {
            strokeWidth: gauge.shift ? 13 : 5
            strokeColor: gauge.shift ? Theme.gaugeShift : Theme.gaugeArc
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: gauge.r; centerY: gauge.r
                radiusX: gauge.r * 0.92; radiusY: gauge.r * 0.92
                startAngle: 90 + (360 - gauge.angleRange) / 2
                sweepAngle: Math.max(0.1, gauge.angleRange * gauge.shownFrac)
            }
        }
    }

    // floating needle: stops short of the centre digit, no hub
    Item {
        anchors.fill: parent
        rotation: gauge.zeroAngle + gauge.angleRange * gauge.shownFrac
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: gauge.r * 0.14
            width: 4
            height: gauge.r * 0.56
            radius: 2
            color: gauge.shift ? Theme.gaugeShift : Theme.gaugeNeedle
        }
    }

    // centre digit / SHIFT!
    Text {
        visible: gauge.showDigitalValue
        anchors.centerIn: parent
        text: gauge.shift ? "SHIFT!" : gauge.fmtValue(gauge.value)
        font.family: Theme.fontBold
        font.bold: true
        font.pixelSize: gauge.shift ? 64 : 78
        color: gauge.shift ? Theme.gaugeShiftText
             : (gauge.redlineFrom > 0 && gauge.value > gauge.redlineFrom
                ? Theme.gaugeRedline : Theme.gaugeCenter)
    }

    // quiet sub-label (SPEED / RPM) and unit (KM/H / X1000) under the digit
    Text {
        visible: gauge.showDigitalValue
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - (0.24 * parent.height + 15) - height / 2
        text: gauge.title
        font.family: Theme.fontMono
        font.pixelSize: 36
        color: Theme.gaugeSub
    }
    Text {
        visible: gauge.showDigitalValue
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - (0.165 * parent.height + 12) - height / 2
        text: gauge.subtitle
        font.family: Theme.fontMono
        font.pixelSize: 24
        color: Theme.gaugeUnit
    }
}
