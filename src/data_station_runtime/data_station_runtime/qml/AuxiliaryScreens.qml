import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    required property var telemetry
    property color amber: "#e5b947"
    property color muted: "#8b98a8"
    property var driverKeys: ["soc", "lv", "tempBattery", "tempMotor", "tempInverter", "hvCurrent", "lvCurrent", "apps", "brake"]

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 9

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            Text { text: "LART"; color: amber; font.pixelSize: 25; font.weight: Font.Bold; font.letterSpacing: 3 }
            Text { text: "DATA STATION"; color: "#eff2f6"; font.pixelSize: 13; font.letterSpacing: 1.5 }
            Item { Layout.fillWidth: true }
            Rectangle {
                Layout.preferredWidth: 123
                Layout.preferredHeight: 28
                radius: 4
                color: telemetry.ready === "READY" ? "#153e2e" : "#252d38"
                Text { anchors.centerIn: parent; text: telemetry.ready; color: telemetry.ready === "READY" ? "#78e7af" : "#c3ccd7"; font.pixelSize: 12; font.weight: Font.Bold }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            spacing: 6
            Repeater {
                model: ["DRIVER", "AUTONOMOUS", "SIGNALS"]
                Rectangle {
                    required property int index
                    required property string modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    radius: 4
                    color: dashboard.screen === index ? "#293441" : "#171d25"
                    border.color: dashboard.screen === index ? amber : "#303a47"
                    Text { anchors.centerIn: parent; text: modelData; color: dashboard.screen === index ? amber : "#b7c1ce"; font.pixelSize: 12; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                    MouseArea { anchors.fill: parent; onClicked: dashboard.selectScreen(index) }
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: dashboard.screen - 1

            GridLayout {
                columns: 4
                rowSpacing: 8
                columnSpacing: 8
                Repeater {
                    model: telemetry.autonomous
                    MetricCard {
                        required property var modelData
                        metric: modelData
                        accent: "#8bd8f7"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                    }
                }
            }

            ColumnLayout {
                id: inspector
                spacing: 6
                property var filtered: {
                    const needle = search.text.toLowerCase()
                    return telemetry.signals.filter(function(row) { return row.id.toLowerCase().indexOf(needle) >= 0 })
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    color: "#171d25"
                    radius: 4
                    border.color: "#3c4b5e"
                    TextInput { id: search; anchors.fill: parent; anchors.margins: 8; color: "#eff2f6"; font.pixelSize: 13; clip: true; selectByMouse: true }
                    Text { anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: "Search bus / message / signal"; visible: !search.text && !search.activeFocus; color: muted; font.pixelSize: 13 }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.rightMargin: 12
                    Text { text: "SIGNAL"; color: muted; font.pixelSize: 10; Layout.fillWidth: true }
                    Text { text: "VALUE / CHOICE"; color: muted; font.pixelSize: 10; Layout.preferredWidth: 220; horizontalAlignment: Text.AlignRight }
                    Text { text: "STATE"; color: muted; font.pixelSize: 10; Layout.preferredWidth: 67; horizontalAlignment: Text.AlignRight }
                    Text { text: "AGE"; color: muted; font.pixelSize: 10; Layout.preferredWidth: 48; horizontalAlignment: Text.AlignRight }
                }
                ListView {
                    id: signalsList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: inspector.filtered
                    spacing: 2
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {
                        width: 6
                        contentItem: Rectangle { implicitWidth: 6; implicitHeight: 28; radius: 3; color: "#52637a" }
                        background: Rectangle { color: "#101721" }
                    }
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: signalsList.width
                        height: 36
                        color: index % 2 ? "#111821" : "#171d25"
                        radius: 3
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 7
                            anchors.rightMargin: 19
                            spacing: 8
                            Text { text: modelData.id; color: modelData.valid ? "#d3dbe5" : muted; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
                            Text { text: modelData.displayValue + (modelData.unit ? " " + modelData.unit : "") + (modelData.choice ? " · " + modelData.choice : ""); color: modelData.valid ? "#eff2f6" : muted; font.pixelSize: 12; elide: Text.ElideRight; Layout.preferredWidth: 220; horizontalAlignment: Text.AlignRight }
                            Text { text: modelData.status; color: modelData.valid ? "#78e7af" : modelData.seen ? amber : muted; font.pixelSize: 10; Layout.preferredWidth: 67; horizontalAlignment: Text.AlignRight }
                            Text { text: modelData.ageText; color: muted; font.pixelSize: 11; Layout.preferredWidth: 48; horizontalAlignment: Text.AlignRight }
                        }
                    }
                    Text { anchors.centerIn: parent; visible: signalsList.count === 0; text: "No matching signals"; color: muted; font.pixelSize: 14 }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            color: telemetry.alerts.some(function(alert) { return alert.severity === "error" }) ? "#3c1820" : telemetry.warning ? "#332b17" : "#141c25"
            border.color: telemetry.warning ? amber : "#303a47"
            radius: 4
            Text {
                anchors.fill: parent
                anchors.margins: 9
                text: telemetry.precharge.visible ? "PRECHARGE · " + telemetry.precharge.text + (telemetry.warning ? " | " + telemetry.warning : "") : telemetry.warning || "NO ACTIVE ALERTS"
                color: telemetry.warning || telemetry.precharge.visible ? amber : muted
                font.pixelSize: 12
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 14
            Text { text: telemetry.freshCount + " LIVE"; color: "#78e7af"; font.pixelSize: 10 }
            Text { text: "  " + telemetry.staleCount + " STALE"; color: telemetry.staleCount ? amber : muted; font.pixelSize: 10 }
            Text { text: "  " + telemetry.unseenCount + " UNSEEN"; color: muted; font.pixelSize: 10 }
            Item { Layout.fillWidth: true }
            Text { text: dashboard.health; color: muted; font.pixelSize: 10; elide: Text.ElideRight; Layout.maximumWidth: 360 }
            Text { text: telemetry.signalCount + " SIGNALS"; color: muted; font.pixelSize: 10 }
        }
    }

}
