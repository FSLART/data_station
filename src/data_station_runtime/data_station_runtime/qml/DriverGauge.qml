import QtQuick

Rectangle {
    id: gauge
    required property var telemetry
    signal nextScreen()
    color: "#050505"
    FontLoader { id: boldFont; source: "assets/Orbitron-Bold.ttf" }
    FontLoader { id: regularFont; source: "assets/Orbitron-Regular.ttf" }

    GaugeCard { y: 70; title: "MOTOR TEMP"; unit: "°C"; metric: gauge.telemetry.driver.tempMotor; family: boldFont.name }
    GaugeCard { y: 202; title: "INV TEMP"; unit: "°C"; metric: gauge.telemetry.driver.tempInverter; family: boldFont.name }
    GaugeCard { y: 334; title: "BAT TEMP"; unit: "°C"; metric: gauge.telemetry.driver.tempBattery; family: boldFont.name }
    GaugeCard { y: 70; rightSide: true; title: "LV"; metric: gauge.telemetry.driver.lv; family: boldFont.name }
    GaugeCard { y: 202; rightSide: true; title: "SOC"; unit: "%"; metric: gauge.telemetry.driver.soc; family: boldFont.name }
    Rectangle {
        x: 554; y: 334; width: 240; height: 116
        radius: 2; border.width: 2; border.color: "#555555"
        gradient: Gradient {
            GradientStop { position: 0; color: "#171717" }
            GradientStop { position: 1; color: "#4c4c4c" }
        }
        Repeater {
            model: ["apps", "brake"]
            Item {
                required property string modelData
                required property int index
                x: 68; y: index * 56; width: 160; height: 50
                property var metric: gauge.telemetry.driver[modelData]
                GaugeLabel {
                    y: 6; width: 160
                    text: modelData.toUpperCase() + " " + (parent.metric.valid ? parent.metric.text + "%" : "—")
                    family: boldFont.name
                }
                Rectangle {
                    x: 0; y: 32; width: 160; height: 18
                    color: "#111111"; border.width: 1; border.color: "#777777"; radius: 2
                    Rectangle {
                        x: 3; y: 3; height: 12
                        width: 154 * Math.max(0, Math.min(1, (metric.value || 0) / 100))
                        radius: 1
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#ffd32a" }
                            GradientStop { position: 1; color: "#ba8e0c" }
                        }
                    }
                }
            }
        }
    }
    Rectangle {
        id: dial
        objectName: "gaugeDial"
        x: 164; y: 4; width: 472; height: 472
        radius: 236; color: "#444444"
        Rectangle {
            x: 7; y: 7; width: 458; height: 458; radius: 229
            gradient: Gradient {
                GradientStop { position: 0; color: "#161616" }
                GradientStop { position: 1; color: "#36332e" }
            }
        }
        Rectangle { x: 19; y: 19; width: 434; height: 434; radius: 217; color: "#2b2824"; border.width: 2; border.color: "#b5b5b5" }
        Canvas {
            anchors.fill: parent
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = "#e51b23"; ctx.lineWidth = 56; ctx.lineCap = "butt"
                ctx.beginPath(); ctx.arc(236, 236, 184, 337 * Math.PI / 180, 405 * Math.PI / 180); ctx.stroke()
                ctx.strokeStyle = "#dddddd"
                for (let i = 0; i <= 40; ++i) {
                    const angle = (135 + i * 6.75) * Math.PI / 180
                    const inner = i % 4 === 0 ? 197 : 205
                    ctx.lineWidth = i % 4 === 0 ? 4 : 1
                    ctx.beginPath(); ctx.moveTo(236 + 212 * Math.cos(angle), 236 + 212 * Math.sin(angle))
                    ctx.lineTo(236 + inner * Math.cos(angle), 236 + inner * Math.sin(angle)); ctx.stroke()
                }
            }
        }
        Repeater {
            model: 11
            GaugeLabel {
                required property int index
                x: Math.floor(236 + 177 * Math.cos((135 + index * 27) * Math.PI / 180)) - 27
                y: Math.floor(236 + 177 * Math.sin((135 + index * 27) * Math.PI / 180)) - 17
                width: 54; text: (index * 2).toString(); font.pixelSize: 30; family: boldFont.name
            }
        }
        Rectangle { x: 80; y: 80; width: 312; height: 312; radius: 156; color: "#030303"; border.width: 8; border.color: "#111111" }
        Image {
            x: 137; y: 133; width: 198; height: 50
            source: "assets/lart-logo-principal.png"
            MouseArea { anchors.fill: parent; onClicked: gauge.nextScreen() }
        }
        Canvas {
            id: needle
            objectName: "gaugeNeedle"
            anchors.fill: parent
            property real rpm: Math.min(20000, Math.abs(gauge.telemetry.driver.rpm.value || 0))
            onRpmChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                if (!gauge.telemetry.driver.rpm.valid) return
                const angle = (135 + 270 * rpm / 20000) * Math.PI / 180
                ctx.strokeStyle = "#ff272e"; ctx.lineWidth = 7; ctx.lineCap = "round"
                ctx.beginPath(); ctx.moveTo(236, 236); ctx.lineTo(236 + 190 * Math.cos(angle), 236 + 190 * Math.sin(angle)); ctx.stroke()
            }
            Connections { target: gauge; function onTelemetryChanged() { needle.requestPaint() } }
        }
        Rectangle { x: 224; y: 224; width: 24; height: 24; radius: 12; color: "#b90b12"; border.width: 2; border.color: "#555555" }
        Rectangle {
            x: 130; y: 188; width: 212; height: 96; radius: 4
            color: "#161616"; border.width: 2; border.color: "#555555"
            GaugeLabel {
                x: 0; y: 4; width: 208
                text: gauge.telemetry.driver.speed.text
                family: boldFont.name; font.pixelSize: 50
            }
            GaugeLabel { x: 0; y: 67; width: 208; text: "km/h"; family: boldFont.name; color: "white" }
        }
        GaugeLabel { x: 173; y: 423; width: 126; text: "RPM x 1000"; family: regularFont.name; font.weight: Font.Normal; color: "#aaaaaa" }
        GaugeLabel {
            x: 116; y: 326; width: 240
            text: gauge.telemetry.ready
            family: boldFont.name; font.pixelSize: 20
            color: gauge.telemetry.ready === "READY" ? "#3fff00" : "#ffd32a"
        }
    }
    GaugeWarning { x: 8; kind: 0; caption: "TEMP"; active: gauge.telemetry.gauge.temperature; family: boldFont.name }
    GaugeWarning { x: 124; kind: 1; caption: "DRIVE"; active: gauge.telemetry.gauge.drive; family: boldFont.name }
    GaugeWarning { x: 572; kind: 2; caption: "LOW SOC"; active: gauge.telemetry.gauge.soc; family: boldFont.name }
    GaugeWarning { x: 688; kind: 3; caption: "LOW LV"; active: gauge.telemetry.gauge.lv; family: boldFont.name }
    Rectangle {
        objectName: "gaugeWarningBanner"
        x: 6; y: 452; width: 788; height: 28; radius: 2
        visible: !!gauge.telemetry.gauge.warning
        color: gauge.telemetry.gauge.drive ? "#050505" : "#33050505"
        border.width: 2
        border.color: gauge.telemetry.gauge.drive ? "#ff272e" : "#33ffd32a"
        clip: true
        Item {
            id: messageTrack
            x: 0; y: 2; width: 784; height: 22
            property real offset: 0
            property bool overflowing: faultText.implicitWidth > width
            property real textWidth: Math.max(width, faultText.implicitWidth)
            GaugeLabel {
                id: faultText
                x: messageTrack.offset; width: messageTrack.textWidth; height: 22
                text: gauge.telemetry.gauge.warning; family: boldFont.name
                color: gauge.telemetry.gauge.drive ? "#ff272e" : "#ffd32a"
                scale: 1
            }
            GaugeLabel {
                x: messageTrack.offset + messageTrack.textWidth + 40
                width: messageTrack.textWidth; height: 22
                visible: messageTrack.overflowing
                text: faultText.text; family: boldFont.name; color: faultText.color; scale: 1
            }
            SequentialAnimation on offset {
                running: messageTrack.parent.visible && messageTrack.overflowing
                loops: Animation.Infinite
                onRunningChanged: if (!running) messageTrack.offset = 0
                PauseAnimation { duration: 1000 }
                NumberAnimation {
                    from: 0; to: -(messageTrack.textWidth + 40)
                    duration: (messageTrack.textWidth + 40) * 1000 / 30
                }
                ScriptAction { script: messageTrack.offset = 0 }
            }
        }
    }
}
