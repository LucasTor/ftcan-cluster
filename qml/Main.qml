import QtQuick

// Dashboard host (cluster.py Dashboard): one swappable content layout under
// the global overlays (tell-tales, night dim, alarm banner). All layouts are
// built up front so switching is instant and never re-runs the intro sweeps.
// The active index lives Python-side (sensors.active_layout) so the stalk
// flash-and-hold gesture and the bench 'L' key share one code path.
Rectangle {
    id: root
    width: Theme.windowWidth
    height: Theme.windowHeight
    color: Theme.bg
    focus: true
    // DEV desktop preview: the whole cluster scaled into a half-size window
    scale: dev_scale
    transformOrigin: Item.TopLeft

    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_L) {          // 'L' cycles layouts (dev / bench)
            sensors.next_layout()
            event.accepted = true
        } else if (event.key === Qt.Key_N) {   // 'N' toggles night mode (dev / bench)
            sensors.toggle_night()
            event.accepted = true
        }
    }

    // Layouts ride an infinite vertical carousel. carouselPos is a continuous
    // position that only ever advances, so every switch — including the
    // 2 -> 0 wrap — slides up; each slot sits at its wrapped offset in
    // [-1.5, +1.5) screen-heights from the animated position, and the slot
    // that jumps from one side to the other does so fully off-screen.
    // Off-screen slots stop rendering entirely — the hidden map must not
    // paint. Slides only animate once live (no strip settling during boot).
    // carouselTarget is the integer destination; carouselPos animates toward
    // it. Assign absolutely, never increment carouselPos — mid-animation it
    // reads back as the fractional in-flight value, and a fast second switch
    // would bake that fraction in (layouts settling cut in half).
    property real carouselPos: 0
    property int carouselTarget: 0
    property int _lastActive: 0
    Component.onCompleted: {
        carouselTarget = sensors.active_layout
        carouselPos = sensors.active_layout
        _lastActive = sensors.active_layout
    }
    Connections {
        target: sensors
        function onLayoutChanged() {
            const a = sensors.active_layout
            root.carouselTarget += ((a - root._lastActive) % 3 + 3) % 3
            root._lastActive = a
            root.carouselPos = root.carouselTarget
        }
    }
    Behavior on carouselPos {
        enabled: sensors.live
        NumberAnimation { duration: 600; easing.type: Easing.OutCubic }
    }

    component LayoutSlot: Item {
        property int index: 0
        width: root.width
        height: root.height
        // clip: the map projects road geometry ~160px past its slot bottom
        // (the behind-the-car near field); the Kivy build relied on the window
        // edge to cut it, here the slot boundary must do it
        clip: true
        readonly property real rel: {
            const r = (((index - root.carouselPos) % 3) + 3) % 3
            return r > 1.5 ? r - 3 : r
        }
        y: rel * root.height
        visible: y > -root.height && y < root.height
    }
    LayoutSlot { index: 0; StreetLayout {} }
    LayoutSlot { index: 1; DetailLayout {} }
    LayoutSlot { index: 2; MapLayout {} }

    // night mode is palette-level: Theme dims informational colours in place
    // (no veil), so tell-tales and alarms stay full-brightness at night
    Binding { target: Theme; property: "night"; value: sensors.night }

    // global overlays — declared after the layouts so they draw on top
    TopAlerts { y: 24 }
    AlarmBar {}
}
