import QtQuick

// Minimal centre readout, no box (widgets/center_info.py). Top: a quiet mono
// micro-grid (temps / pressures / level / flex blend). Then the EGT balance
// row (4 cylinder dots, green in balance, reddening as a channel deviates from
// the group median), then hairline-split big BOOST and LAMBDA values.
// Values show "—" until the render loop goes live, like the Kivy build.
Item {
    id: card
    width: Theme.cardWidth
    height: Theme.cardHeight
    x: (Theme.windowWidth - width) / 2
    // (WINDOW_HEIGHT/2) - (h/2) - CENTER_Y_OFFSET in Kivy bottom-up coords
    y: Theme.windowHeight - ((Theme.windowHeight / 2) - (height / 2) - 32) - height

    readonly property bool live: sensors.live

    // ---- EGT balance helpers (ported verbatim from center_info.py) ----
    readonly property var egts: [sensors.egt1, sensors.egt2, sensors.egt3, sensors.egt4]
    readonly property bool egtActive: Math.max(...egts) > Theme.egtActiveMin
    readonly property real egtMedian: {
        const s = [...egts].sort((a, b) => a - b)
        return (s[1] + s[2]) / 2
    }
    function egtLerp(a, b, k) {
        return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k,
                       a.b + (b.b - a.b) * k, a.a + (b.a - a.a) * k)
    }
    // green -> amber -> red, routed through amber so mid-range stays clean
    function egtColor(k) {
        if (k <= 0.5)
            return egtLerp(Theme.egtBalanced, Theme.egtMid, k * 2.0)
        return egtLerp(Theme.egtMid, Theme.egtUnbalanced, (k - 0.5) * 2.0)
    }

    readonly property real egtAvg: (egts[0] + egts[1] + egts[2] + egts[3]) / 4

    // One micro-grid cell: label over value. Cells are static instances (not a
    // per-tick model) so only the value/warn bindings — each depending on its
    // own sensor — re-evaluate; the delegates are never rebuilt.
    component MicroCell: Column {
        property string label
        property string value
        property bool warn: false
        property color warnColor: Theme.ttRed
        width: (card.width - 20 - 3 * 10) / 4
        spacing: 2
        Text {
            width: parent.width
            height: 22
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: parent.label
            font.family: Theme.fontMono
            font.pixelSize: 18
            color: Theme.labelDim
        }
        Text {
            width: parent.width
            height: 40
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: card.live ? parent.value : "—"
            font.family: Theme.fontMono
            font.pixelSize: 22
            font.bold: true
            color: parent.warn ? parent.warnColor : Theme.value
        }
    }

    Column {
        x: 10
        y: 8
        width: parent.width - 20
        spacing: 6

        // --- micro-grid: 4 columns x 2 rows ---
        Grid {
            width: parent.width
            height: 134
            columns: 4
            columnSpacing: 10
            rowSpacing: 6
            MicroCell { label: "AIR";    value: Math.round(sensors.air_temp) + " °C"
                        warn: sensors.air_temp > 58; warnColor: Theme.ttAmber }
            MicroCell { label: "ENGINE"; value: Math.round(sensors.engine_temp) + " °C"
                        warn: sensors.engine_temp > 104 }
            MicroCell { label: "OIL";    value: sensors.oil_pressure_bar.toFixed(1) + " BAR" }
            MicroCell { label: "EGT";    value: card.egtActive ? Math.round(card.egtAvg) + " °C" : "—"
                        warn: card.egtActive && card.egtAvg > 750 }
            MicroCell { label: "FUEL P"; value: sensors.fuel_pressure_bar.toFixed(1) + " BAR" }
            MicroCell { label: "LEVEL";  value: Math.round(sensors.fuel_level) + " %" }
            MicroCell { label: "OIL T";  value: Math.round(sensors.oil_temp) + " °C"
                        warn: sensors.oil_temp > 120 }
            MicroCell { label: "FUEL";   value: "E" + Math.round(sensors.ethanol) }
        }

        // --- EGT balance row: 4 cylinder cells (dot over temp), tight cluster ---
        Item {
            width: parent.width
            height: 48
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 14
                Repeater {
                    model: 4
                    delegate: Column {
                        width: 48
                        spacing: 2
                        readonly property real k: card.egtActive
                            ? Math.min(1.0, Math.abs(card.egts[index] - card.egtMedian) / Theme.egtSpreadRed)
                            : 0
                        Item {
                            width: parent.width
                            height: 22
                            Rectangle {
                                anchors.centerIn: parent
                                width: 18; height: 18; radius: 9
                                color: card.egtActive ? card.egtColor(parent.parent.k)
                                                      : Theme.egtInactive
                            }
                        }
                        Text {
                            width: parent.width
                            height: 22
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            text: card.egtActive ? Math.round(card.egts[index]).toString() : "—"
                            font.family: Theme.fontMono
                            font.pixelSize: 18
                            font.bold: true
                            color: card.egtActive ? Theme.value : Qt.rgba(1, 1, 1, 0.25)
                        }
                    }
                }
            }
        }

        // --- hairline / big BOOST / hairline / big LAMBDA ---
        Item {
            width: parent.width; height: 22
            Rectangle {
                anchors.centerIn: parent
                width: 64; height: 1
                color: Theme.hairline
            }
        }

        Item {
            id: boostBlock
            width: parent.width
            height: 176
            readonly property color valueColor:
                sensors.map > 1.32 ? Theme.ttRed : Theme.boostNormal
            // tight glyph bounds — the Kivy build positions the title/unit from
            // the rendered texture height, not the (leading-padded) line box
            TextMetrics {
                id: boostMetrics
                font: boostValue.font
                text: boostValue.text
            }
            readonly property real glyphH: boostMetrics.tightBoundingRect.height
            Text {
                id: boostValue
                anchors.centerIn: parent
                text: card.live ? Math.max(0, sensors.map).toFixed(2) : "0.00"
                font.family: Theme.fontBold
                font.bold: true
                font.pixelSize: 120
                color: card.live ? boostBlock.valueColor : Theme.boostNormal
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height / 2 - boostBlock.glyphH * 0.62 - height - 1
                text: "BOOST"
                font.family: Theme.fontMono
                font.pixelSize: 30
                color: Theme.labelAccent
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height / 2 + boostBlock.glyphH * 0.78 + 1
                text: "BAR"
                font.family: Theme.fontMono
                font.pixelSize: 16
                color: Theme.unitDim
            }
        }

        Item {
            width: parent.width; height: 22
            Rectangle {
                anchors.centerIn: parent
                width: 64; height: 1
                color: Theme.hairline
            }
        }

        Item {
            id: lambdaBlock
            width: parent.width
            height: 176
            // Below ~500 rpm lambda pegs lean on ambient O2 — stay neutral.
            readonly property bool burning: sensors.rpm >= 500
            readonly property color valueColor: !card.live || !burning ? Theme.boostNormal
                : sensors.lambda_afr < 0.85 ? Theme.ttAmber
                : sensors.lambda_afr > 1.05 ? Theme.ttRed
                : Theme.boostNormal
            readonly property string tag: !card.live || !burning ? "STOICH"
                : sensors.lambda_afr < 0.85 ? "RICH"
                : sensors.lambda_afr > 1.05 ? "LEAN"
                : "STOICH"
            TextMetrics {
                id: lambdaMetrics
                font: lambdaValue.font
                text: lambdaValue.text
            }
            readonly property real glyphH: lambdaMetrics.tightBoundingRect.height
            Text {
                id: lambdaValue
                anchors.centerIn: parent
                text: card.live ? sensors.lambda_afr.toFixed(2) : "1.00"
                font.family: Theme.fontBold
                font.bold: true
                font.pixelSize: 120
                color: lambdaBlock.valueColor
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height / 2 - lambdaBlock.glyphH * 0.62 - height - 1
                text: "LAMBDA"
                font.family: Theme.fontMono
                font.pixelSize: 30
                color: Theme.labelAccent
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height / 2 + lambdaBlock.glyphH * 0.78 + 1
                text: lambdaBlock.tag
                font.family: Theme.fontMono
                font.pixelSize: 16
                color: Theme.unitDim
            }
        }
    }
}
