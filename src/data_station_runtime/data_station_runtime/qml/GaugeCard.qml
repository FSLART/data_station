import QtQuick

Rectangle {
    id: card
    property bool rightSide: false
    property string title
    property string unit
    property var metric
    property string family
    width: 240; height: 116
    x: rightSide ? 554 : 6
    radius: 2
    border.width: 2
    border.color: "#555555"
    gradient: Gradient {
        GradientStop { position: 0; color: "#171717" }
        GradientStop { position: 1; color: "#4c4c4c" }
    }
    GaugeLabel {
        x: card.rightSide ? 68 : 8; y: 80; width: 160
        text: card.title; family: card.family; color: "white"
    }
    GaugeLabel {
        x: card.rightSide ? 198 : 8; y: 8; width: 36
        text: card.unit; family: card.family; font.pixelSize: 20
    }
    GaugeLabel {
        x: card.rightSide ? 68 : 8; y: 17; width: 160
        text: card.metric.valid ? card.title === "LV" ? card.metric.text + " V" : Math.round(card.metric.value).toString() : "—"
        family: card.family; font.pixelSize: 40
    }
}
