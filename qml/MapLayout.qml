import QtQuick
import QtQuick.Shapes
import Cluster 1.0

// Perspective map + minimal HUD (widgets/layouts.py MapLayout + the static
// canvas pieces of widgets/map_view.py): road ribbons come from the Python
// MapItem; distance fog, the nav-style car marker and the HUD live here.
Item {
    anchors.fill: parent

    MapItem {
        anchors.fill: parent
        lat: sensors.lat
        lon: sensors.lon
        heading: sensors.heading_deg
        dim: Theme.dim
    }

    // distance fog: transparent -> solid BG rising to the horizon band
    Rectangle {
        x: 0; y: 185; width: parent.width; height: 135
        gradient: Gradient {
            GradientStop { position: 0.0; color: "black" }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }
    Rectangle {
        x: 0; y: 0; width: parent.width; height: 185
        color: "black"
    }

    // --- car marker (fixed anchor at 960, 520): soft radial glow, dark seat,
    //     swept-wing arrow (white rim + Azul Boreal fill). Grouped so palette
    //     night mode can dim it with everything else ---
    Item {
    anchors.fill: parent
    opacity: 1 - Theme.dim * 0.55
    Canvas {
        x: 898; y: 450; width: 124; height: 124
        onPaint: {
            const ctx = getContext("2d")
            const g = ctx.createRadialGradient(62, 62, 0, 62, 62, 62)
            g.addColorStop(0.0, "rgba(90,166,234,0.84)")
            g.addColorStop(0.25, "rgba(90,166,234,0.47)")
            g.addColorStop(0.5, "rgba(90,166,234,0.21)")
            g.addColorStop(0.75, "rgba(90,166,234,0.05)")
            g.addColorStop(1.0, "rgba(90,166,234,0)")
            ctx.fillStyle = g
            ctx.fillRect(0, 0, 124, 124)
        }
    }
    Rectangle {
        x: 930; y: 482; width: 60; height: 60; radius: 30
        color: Qt.rgba(0, 0, 0, 0.55)
    }
    Shape {
        ShapePath {   // outer silhouette (white rim)
            strokeWidth: -1
            fillColor: Qt.rgba(0.949, 0.957, 0.973, 1.0)
            startX: 960; startY: 481.5
            PathLine { x: 984; y: 540 }
            PathLine { x: 960; y: 530.5 }
            PathLine { x: 936; y: 540 }
            PathLine { x: 960; y: 481.5 }
        }
        ShapePath {   // inner fill (Azul Boreal), inset for an even rim
            strokeWidth: -1
            fillColor: Qt.rgba(0.420, 0.706, 0.945, 1.0)
            startX: 960; startY: 487
            PathLine { x: 979.5; y: 535.5 }
            PathLine { x: 960; y: 527.5 }
            PathLine { x: 940.5; y: 535.5 }
            PathLine { x: 960; y: 487 }
        }
    }
    }

    // --- HUD: wheel speed (bottom-left; the trusted speed source), compass
    //     heading (top-right) ---
    Text {
        x: 60; y: 470; width: 320; height: 150
        verticalAlignment: Text.AlignVCenter
        text: Math.round(sensors.wheel_speed_fl_kmh).toString()
        font.family: Theme.fontLight
        font.pixelSize: 130
        color: Theme.gaugeCenter
    }
    Text {
        x: 64; y: 624; width: 320; height: 24
        verticalAlignment: Text.AlignVCenter
        text: "KM/H"
        font.family: Theme.fontMono
        font.pixelSize: 20
        color: Theme.labelAccent
    }
    // current street name (from the baked map_names.json layer; fades out
    // when off the mapped grid) — bottom-right, sharing the compass margin
    Text {
        x: 1052; y: 662; width: 820; height: 34
        horizontalAlignment: Text.AlignRight
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideLeft
        text: sensors.street_name
        font.family: Theme.fontMain
        font.bold: true
        font.pixelSize: 29
        color: Theme.text
        opacity: sensors.street_name ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 350 } }
    }
    Text {
        x: 1612; y: 60; width: 260; height: 30
        horizontalAlignment: Text.AlignRight
        verticalAlignment: Text.AlignVCenter
        text: {
            const hdg = ((sensors.heading_deg % 360) + 360) % 360
            const card = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][
                Math.floor(((hdg + 22.5) % 360) / 45)]
            return card + " " + ("00" + Math.round(hdg)).slice(-3) + "°"
        }
        font.family: Theme.fontMono
        font.pixelSize: 26
        color: Theme.labelAccent
    }
    // now playing (top-left, inside the horizon fog band)
    NowPlaying {}
}
