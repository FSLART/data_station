import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: window
    width: 800
    height: 480
    minimumWidth: 800
    minimumHeight: 480
    visible: true
    color: "#050505"
    title: "LART Data Station"
    property var telemetry: dashboard.state

    Shortcut { sequence: "1"; onActivated: dashboard.selectScreen(0) }
    Shortcut { sequence: "2"; onActivated: dashboard.selectScreen(1) }
    Shortcut { sequence: "3"; onActivated: dashboard.selectScreen(2) }
    Shortcut { sequence: "Right"; onActivated: dashboard.selectScreen((dashboard.screen + 1) % 3) }
    Shortcut { sequence: "Left"; onActivated: dashboard.selectScreen((dashboard.screen + 2) % 3) }

    Item {
        width: 800
        height: 480
        anchors.centerIn: parent
        scale: Math.min(window.width / width, window.height / height)

        DriverGauge {
            anchors.fill: parent
            visible: dashboard.screen === 0
            telemetry: window.telemetry
            onNextScreen: dashboard.selectScreen(1)
        }
        AuxiliaryScreens { anchors.fill: parent; visible: dashboard.screen !== 0; telemetry: window.telemetry }
        Rectangle {
            x: 0; y: 360; width: 800; height: 120
            visible: window.telemetry.precharge.visible
            color: window.telemetry.precharge.color
            opacity: 0.8
        }
        GaugeLabel {
            x: 20; y: 360; width: 760; height: 120
            visible: window.telemetry.precharge.visible
            text: window.telemetry.precharge.text
            color: "white"
            family: overlayFont.name
            font.pixelSize: window.telemetry.precharge.hvOn ? 50 : 30
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
            scale: 1
        }
    }
    FontLoader { id: overlayFont; source: "assets/Orbitron-Bold.ttf" }
}
