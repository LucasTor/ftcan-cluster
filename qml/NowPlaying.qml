import QtQuick

// Persistent now-playing for the map layout: album cover (placeholder disc
// until AVRCP cover art / BlueZ >= 5.79), track title and artist. Top-left
// corner — inside the horizon fog band, which is solid background, so it sits
// chip-less like the map's other HUD corners (speed / compass / coords).
// Only present while a phone is connected with a track; fades rather than
// popping.
Item {
    id: np
    readonly property bool active: sensors.bt_connected
                                   && sensors.track_title !== ""
    readonly property real textW: Math.min(500, Math.max(t1.implicitWidth,
                                                         t2.implicitWidth))
    x: 48
    y: 52
    width: 72 + 18 + textW
    height: 72
    opacity: active ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 400 } }
    visible: opacity > 0.01

    Rectangle {   // album cover (real art when fetched, placeholder disc else)
        width: 72
        height: 72
        radius: 10
        color: Qt.rgba(1, 1, 1, 0.05)
        border.width: 1
        border.color: Theme.hairline
        Image {
            id: cover
            anchors.fill: parent
            anchors.margins: 1
            source: sensors.track_art_path
                    ? "file://" + sensors.track_art_path : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            // cross-fade with the placeholder disc when the download lands
            opacity: status === Image.Ready ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 350 } }
        }
        Text {
            anchors.centerIn: parent
            opacity: 1 - cover.opacity
            visible: opacity > 0.01
            text: String.fromCodePoint(sensors.media_art_icon)
            font.family: Theme.fontIcons
            font.pixelSize: 40
            color: Theme.labelDim
        }
    }
    Text {
        id: t1
        x: 90; y: 5
        width: np.textW
        elide: Text.ElideRight
        text: sensors.track_title
        font.family: Theme.fontMain
        font.bold: true
        font.pixelSize: 29
        color: Theme.value
    }
    Text {
        id: t2
        x: 90; y: 43
        width: np.textW
        elide: Text.ElideRight
        text: sensors.track_artist
        font.family: Theme.fontMono
        font.pixelSize: 19
        color: Theme.labelAccent
    }
}
