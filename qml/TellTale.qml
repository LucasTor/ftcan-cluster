import QtQuick

// A single bare tell-tale: an MDI icon glyph, no outline (widgets/top_alerts.py).
Item {
    id: tale
    property int icon: 0             // MDI codepoint
    property color onColor: Theme.ttBlue
    property bool lit: false
    property color litColor: onColor // per-frame override (lambda rich/lean)

    width: 48
    height: 40

    Text {
        anchors.centerIn: parent
        text: String.fromCodePoint(tale.icon)
        font.family: Theme.fontIcons
        font.pixelSize: 32
        color: tale.lit ? tale.litColor : Theme.pillOffText
    }
}
