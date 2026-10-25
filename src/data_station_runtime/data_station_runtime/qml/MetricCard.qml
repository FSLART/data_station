import QtQuick
import QtQuick.Layouts

Rectangle {
    id: card
    property var metric: ({label: "", text: "—", unit: "", valid: false})
    property color accent: "#e5b947"
    color: "#171d25"
    radius: 6
    border.color: "#303a47"
    implicitWidth: 130
    implicitHeight: 78

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 3
        Text {
            Layout.fillWidth: true
            text: card.metric.label
            color: "#b7c1ce"
            font.pixelSize: 11
            font.letterSpacing: 0.8
            elide: Text.ElideRight
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 5
            Text {
                Layout.fillWidth: true
                text: card.metric.text
                color: card.metric.valid ? card.accent : "#778391"
                font.pixelSize: 25
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                minimumPixelSize: 14
                fontSizeMode: Text.Fit
            }
            Text {
                text: card.metric.unit
                color: "#b7c1ce"
                font.pixelSize: 11
                Layout.alignment: Qt.AlignBottom
                Layout.bottomMargin: 5
            }
        }
    }
}
