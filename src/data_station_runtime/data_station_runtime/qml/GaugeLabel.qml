import QtQuick

Text {
    property string family
    font.family: family
    font.weight: Font.Bold
    font.pixelSize: 15
    color: "#ffd32a"
    horizontalAlignment: Text.AlignHCenter
    scale: 282 / 256
    transformOrigin: Item.Center
}
