import QtQuick

// Compact stat tile (widgets/stat_tile.py): label · big value · full-width
// bottom bar showing where the value sits in range — bright-cyan fill on a
// dark-teal track with min / unit / max sitting on the bar.
Rectangle {
    id: tile
    property string label: ""
    property string unit: ""
    property real vmin: 0
    property real vmax: 100
    property int decimals: 1
    property string prefix: ""
    property var warnFn: null          // v => bool, or null
    property color warnColor: tileValueCol
    property real value: 0

    readonly property color tileValueCol: Theme.d(Qt.rgba(0.97, 0.98, 1.0, 1.0))
    readonly property bool warn: warnFn !== null && sensors.live && warnFn(value)
    readonly property real frac: vmax > vmin
        ? Math.max(0, Math.min(1, (value - vmin) / (vmax - vmin))) : 0

    width: 282
    height: 180
    color: "black"
    radius: 6
    border.color: Theme.d(Qt.rgba(0.32, 0.60, 0.72, 0.30))
    border.width: 1.3

    // bottom bar: dark-teal track + cyan (or warn-colour) fill
    Rectangle {
        x: 1; width: parent.width - 2
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 1
        height: 26
        color: Theme.d(Qt.rgba(0.055, 0.290, 0.360, 1.0))
        Rectangle {
            width: parent.width * tile.frac
            height: parent.height
            color: tile.warn ? tile.warnColor : Theme.d(Qt.rgba(0.078, 0.784, 1.0, 1.0))
        }
        Text {
            anchors.left: parent.left; anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: Number(tile.vmin).toLocaleString(Qt.locale("C"), "g", 6)
            font.family: Theme.fontMain; font.pixelSize: 14
            color: Theme.d(Qt.rgba(0.90, 0.93, 0.96, 0.95))
        }
        Text {
            anchors.centerIn: parent
            text: tile.unit
            font.family: Theme.fontMain; font.pixelSize: 13
            color: Theme.d(Qt.rgba(0.62, 0.78, 0.85, 0.85))
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: Number(tile.vmax).toLocaleString(Qt.locale("C"), "g", 6)
            font.family: Theme.fontMain; font.pixelSize: 14
            color: Theme.d(Qt.rgba(0.90, 0.93, 0.96, 0.95))
        }
    }

    Text {   // label (top; box centre 21px below the top edge)
        anchors.horizontalCenter: parent.horizontalCenter
        y: 21 - height / 2
        text: tile.label
        font.family: Theme.fontMain; font.pixelSize: 19
        color: Theme.d(Qt.rgba(0.80, 0.84, 0.88, 0.92))
    }

    Text {   // big value (fills the middle above the bar; box centre at 83px)
        anchors.horizontalCenter: parent.horizontalCenter
        y: 83 - height / 2
        text: sensors.live ? tile.prefix + tile.value.toFixed(tile.decimals) : "—"
        font.family: Theme.fontBold
        font.bold: true
        font.pixelSize: 78
        color: tile.warn ? tile.warnColor : tile.tileValueCol
    }
}
