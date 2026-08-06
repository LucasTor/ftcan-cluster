import QtQuick

// Transient now-playing / phone-connected toast, bottom-centre of every
// layout. The envelope (fade in / hold / fade out) and the two lines are
// computed Python-side by decisions.MediaToast; this only renders
// sensors.toast_*. Hidden on the map layout (it has its own persistent
// NowPlaying — showing both would double the same song). The art square is a
// placeholder disc until AVRCP cover art lands (BlueZ >= 5.79, stage 2).
Rectangle {
    id: toast
    readonly property real textW: Math.min(560, Math.max(l1.implicitWidth,
                                                         l2.implicitWidth))
    width: 16 + 60 + 16 + textW + 20
    height: 84
    radius: 14
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 16
    color: Qt.rgba(0.016, 0.024, 0.04, 0.94)
    border.width: 1
    border.color: Theme.hairline
    opacity: sensors.toast_alpha * (sensors.active_layout === 2 ? 0 : 1)
    visible: opacity > 0.01

    Rectangle {   // album art (real cover when fetched, placeholder disc else)
        x: 16
        anchors.verticalCenter: parent.verticalCenter
        width: 60
        height: 60
        radius: 8
        color: Qt.rgba(1, 1, 1, 0.05)
        border.width: 1
        border.color: Theme.hairline
        Image {
            id: toastCover
            anchors.fill: parent
            anchors.margins: 1
            source: sensors.track_art_path
                    ? "file://" + sensors.track_art_path : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            // fade IN only: the toast announces the new track, so the old
            // cover must vanish instantly (snap down), never linger fading
            // out under the new title. The map's NowPlaying keeps the
            // symmetric cross-fade — it's a persistent element.
            opacity: status === Image.Ready ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity {
                enabled: toastCover.opacity < 0.99   // animate upward only
                NumberAnimation { duration: 350 }
            }
        }
        Text {
            anchors.centerIn: parent
            opacity: 1 - toastCover.opacity
            visible: opacity > 0.01
            text: String.fromCodePoint(sensors.media_art_icon)
            font.family: Theme.fontIcons
            font.pixelSize: 34
            color: Theme.labelDim
        }
    }
    Text {
        id: l1
        x: 92; y: 12
        width: toast.textW
        elide: Text.ElideRight
        text: sensors.toast_line1
        font.family: Theme.fontMain
        font.bold: true
        font.pixelSize: 26
        color: Theme.value
    }
    Text {
        id: l2
        x: 92; y: 47
        width: toast.textW
        elide: Text.ElideRight
        text: sensors.toast_line2
        font.family: Theme.fontMono
        font.pixelSize: 17
        color: Theme.labelAccent
    }
}
