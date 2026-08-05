import QtQuick

// The minimal twin-dial view: SPEED (left) + RPM (right) + centre card
// (widgets/layouts.py StreetLayout).
Item {
    anchors.fill: parent

    Gauge {
        x: 60; y: 60
        title: "SPEED"; subtitle: "KM/H"
        maxValue: 240
        ticks: 13
        value: sensors.wheel_speed_fl_kmh
    }

    Gauge {
        x: 1260; y: 60
        title: "RPM"; subtitle: "X1000"
        maxValue: 8000
        ticks: 9
        redlineFrom: 5500
        formatMode: "rpm"
        labelMap: ({1000: "1", 2000: "2", 3000: "3", 4000: "4",
                    5000: "5", 6000: "6", 7000: "7", 8000: "8"})
        value: sensors.rpm
        shift: sensors.rpm >= 6000
    }

    CenterInfo {}
}
