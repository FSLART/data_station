import QtQuick

Item {
    id: warning
    property int kind
    property bool active: false
    property string caption
    property string family
    property color warningColor: active ? kind === 1 ? "#ff272e" : "#ffd32a" : "#626262"
    width: 104; height: 62; y: 4
    opacity: active ? 1 : 0.2
    Canvas {
        id: icon
        width: 104; height: 43
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = warning.warningColor
            ctx.fillStyle = warning.warningColor
            ctx.lineWidth = 3
            ctx.lineCap = "round"
            const thermometer = [[18,5,18,27],[18,5,24,5],[24,5,24,27],[21,12,21,31],[27,12,31,12],[27,18,33,18],[27,24,31,24],[4,38,9,35],[9,35,14,38],[28,38,33,35],[33,35,38,38]]
            const motor = [[9,10,34,10],[34,10,34,32],[34,32,9,32],[9,32,9,10],[9,15,4,15],[4,15,4,27],[4,27,9,27],[34,20,40,20],[34,24,40,24],[14,16,29,16],[14,22,29,22],[14,28,29,28]]
            const battery = [[3,13,39,13],[39,13,39,35],[39,35,3,35],[3,35,3,13],[9,9,9,13],[32,9,32,13],[9,24,17,24],[13,20,13,28],[27,24,33,24]]
            const strokes = warning.kind === 0 ? thermometer : warning.kind === 1 ? motor : battery
            for (let line of strokes) {
                ctx.beginPath(); ctx.moveTo(31 + line[0], line[1]); ctx.lineTo(31 + line[2], line[3]); ctx.stroke()
            }
            if (warning.kind === 0) {
                ctx.beginPath(); ctx.arc(52, 32, 6, 0, Math.PI * 2); ctx.fill()
            }
            if (warning.kind === 3) {
                ctx.beginPath(); ctx.moveTo(52,1); ctx.lineTo(52,9); ctx.lineTo(48,5); ctx.moveTo(52,9); ctx.lineTo(56,5); ctx.stroke()
            }
        }
        Connections { target: warning; function onWarningColorChanged() { icon.requestPaint() } }
    }
    GaugeLabel {
        x: 0; y: 43; width: 104
        text: warning.caption; family: warning.family; color: warning.warningColor
    }
}
