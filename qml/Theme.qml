pragma Singleton
import QtQuick

// Mirrors theme.py — every QML widget pulls colours/sizes from here so the
// cluster can be restyled in one place. Keep in sync with theme.py while both
// UIs exist.
//
// Night mode is palette-level (unlike the Kivy build's black veil): every
// *informational* colour routes through d(), which scales luminance down to
// ~45% when `night` is set — the veil's overall effect — while *status*
// colours (tell-tales, alarms, shift light, EGT balance) keep full brightness
// so warnings stay crisp at night.
QtObject {
    property bool night: false          // driven from sensors.night (Main.qml)
    property real dim: night ? 1 : 0    // animated master dim factor
    Behavior on dim { NumberAnimation { duration: 600 } }

    function d(c) {
        c = Qt.color(c)
        const k = 1 - dim * 0.55
        return Qt.rgba(c.r * k, c.g * k, c.b * k, c.a)
    }

    readonly property color bg: "black"
    readonly property color accent: d(Qt.rgba(0.353, 0.651, 0.918, 1.0))  // Azul Boreal
    readonly property color text: d("#eceef2")
    readonly property color value: d(Qt.rgba(1, 1, 1, 0.82))
    readonly property color labelDim: d(Qt.rgba(0.353, 0.651, 0.918, 0.70))
    readonly property color labelAccent: d(Qt.rgba(0.353, 0.651, 0.918, 0.95))
    readonly property color unitDim: d(Qt.rgba(0.353, 0.651, 0.918, 0.45))
    readonly property color hairline: d(Qt.rgba(0.353, 0.651, 0.918, 0.28))
    readonly property color boostNormal: d(Qt.rgba(0.420, 0.706, 0.945, 1.0))

    readonly property color ttGreen: "#33d17a"
    readonly property color ttBlue: "#5aa6ea"
    readonly property color ttRed: "#ff5a45"
    readonly property color ttAmber: "#ffb02e"
    readonly property color ttCyan: "#22d3ee"
    readonly property color pillOffBorder: Qt.rgba(1, 1, 1, 0.06)
    readonly property color pillOffText: Qt.rgba(1, 1, 1, 0.10)

    readonly property color lambdaRich: d("#ff8a4d")
    readonly property color lambdaLean: d("#ffd14d")
    readonly property color lambdaStoich: d("#7fd6a3")

    readonly property color egtBalanced: "#33d17a"
    readonly property color egtMid: "#ffc73b"
    readonly property color egtUnbalanced: "#ff3b30"
    readonly property color egtInactive: Qt.rgba(0.353, 0.651, 0.918, 0.16)
    readonly property real egtSpreadRed: 100.0
    readonly property real egtActiveMin: 80.0

    readonly property color alarmBg: Qt.rgba(0.86, 0.07, 0.05, 1.0)
    readonly property color alarmText: "white"

    readonly property color gaugeFace: "black"
    readonly property color gaugeRing: d(Qt.rgba(0.353, 0.651, 0.918, 0.28))
    readonly property color gaugeTick: d(Qt.rgba(0.667, 0.804, 0.945, 0.92))
    readonly property color gaugeTickMinor: d(Qt.rgba(0.353, 0.651, 0.918, 0.28))
    readonly property color gaugeNum: d(Qt.rgba(0.700, 0.820, 0.945, 0.62))
    readonly property color gaugeArc: d(Qt.rgba(0.353, 0.651, 0.918, 0.85))
    readonly property color gaugeNeedle: d(Qt.rgba(0.353, 0.651, 0.918, 1.0))
    readonly property color gaugeRedline: d(Qt.rgba(1.0, 0.353, 0.314, 0.85))
    // shift colours stay full-brightness: the shift light must pop at night
    readonly property color gaugeShift: "#ffd23a"
    readonly property color gaugeShiftText: "#ff3b30"
    readonly property color gaugeShiftFlash: "#ff1810"
    readonly property color gaugeCenter: d("#f2f4f8")
    readonly property color gaugeSub: d(Qt.rgba(0.353, 0.651, 0.918, 0.85))
    readonly property color gaugeUnit: d(Qt.rgba(0.353, 0.651, 0.918, 0.40))

    // fonts (paths relative to this file, so cwd doesn't matter)
    readonly property FontLoader _mono: FontLoader { source: "../fonts/ShareTechMono-Regular.ttf" }
    readonly property FontLoader _light: FontLoader { source: "../fonts/Compagnon-Light.otf" }
    readonly property FontLoader _medium: FontLoader { source: "../fonts/Compagnon-Medium.otf" }
    readonly property FontLoader _icons: FontLoader { source: "../fonts/materialdesignicons-webfont.ttf" }
    readonly property string fontMono: _mono.name
    readonly property string fontLight: _light.name
    // Every Compagnon file reports the SAME family name ("Compagnon") and the
    // Light face mislabels its weight as 400/Normal — so fontMain and
    // fontLight are the identical string, and a plain fontMain request
    // resolves to the Light face. Any fontMain text WITHOUT font.bold must
    // pair with `font.weight: Theme.weightMain` to land on Medium (600);
    // font.bold: true requests 700 and already matches Medium + synthesis.
    readonly property int weightMain: Font.DemiBold
    readonly property string fontMain: _medium.name     // Kivy's registered default
    // Kivy's bold=True synthesizes bold over Medium — pair fontMain with
    // font.bold. (Compagnon-Bold.otf is a decorative outline face, NOT what
    // the Kivy build shows.)
    readonly property string fontBold: _medium.name
    readonly property string fontIcons: _icons.name

    // window / centre card constants
    readonly property int windowWidth: 1920
    readonly property int windowHeight: 720
    readonly property int cardWidth: 450
    readonly property int cardHeight: 600
}
