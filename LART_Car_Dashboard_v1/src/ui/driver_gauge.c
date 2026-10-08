#include <math.h>
#include <stdio.h>
#include "screens.h"
#include "ui.h"
#include "dbc_api.h"
#include "fonts.h"
#include "images.h"

// Display scale only; the red sector is styling, not a motor safety limit.
#define DIAL_MAX_RPM 20000.0f
#define AMBER 0xffd32a
#define WARNING_OFF 0x626262
#define WARNING_ON 0xb0b0b0
#define WARNING_RED 0xff272e

// Dashboard advisories, not protection limits; tune to the installed hardware.
#define LOW_LV_ON_V 24.5f
#define LOW_LV_CLEAR_V 24.8f
#define LOW_SOC_ON_PERCENT 15.0f
#define LOW_SOC_CLEAR_PERCENT 17.0f
#define MOTOR_WARN_C 100.0f
#define INVERTER_WARN_C 80.0f
#define BATTERY_WARN_C 55.0f
#define TEMP_HYSTERESIS_C 5.0f

enum { WARN_TEMP, WARN_DRIVE, WARN_SOC, WARN_LV };
static bool motor_hot, inverter_hot, battery_hot, soc_low, lv_low;
static lv_obj_t *warning_banner;

static lv_obj_t *needle;
static lv_obj_t *ready;
static lv_point_precise_t needle_points[2];
static lv_point_precise_t ticks[41][2];

// Native vector strokes keep the telltales crisp without image assets or fonts.
static void draw_warning_icon(lv_event_t *event) {
    static const int8_t thermometer[][4] = {
        {18, 5, 18, 27}, {18, 5, 24, 5}, {24, 5, 24, 27},
        {21, 12, 21, 31}, {27, 12, 31, 12}, {27, 18, 33, 18},
        {27, 24, 31, 24}, {4, 38, 9, 35}, {9, 35, 14, 38},
        {28, 38, 33, 35}, {33, 35, 38, 38}
    };
    static const int8_t motor[][4] = {
        {9, 10, 34, 10}, {34, 10, 34, 32}, {34, 32, 9, 32},
        {9, 32, 9, 10}, {9, 15, 4, 15}, {4, 15, 4, 27},
        {4, 27, 9, 27}, {34, 20, 40, 20}, {34, 24, 40, 24},
        {14, 16, 29, 16}, {14, 22, 29, 22}, {14, 28, 29, 28}
    };
    static const int8_t battery[][4] = {
        {3, 13, 39, 13}, {39, 13, 39, 35}, {39, 35, 3, 35},
        {3, 35, 3, 13}, {9, 9, 9, 13}, {32, 9, 32, 13},
        {9, 24, 17, 24}, {13, 20, 13, 28}, {27, 24, 33, 24}
    };
    lv_obj_t *obj = lv_event_get_target(event);
    lv_layer_t *layer = lv_event_get_layer(event);
    int kind = (int)(intptr_t)lv_event_get_user_data(event);
    lv_area_t area;
    lv_obj_get_coords(obj, &area);
    const int8_t (*strokes)[4] = kind == WARN_TEMP ? thermometer :
        kind == WARN_DRIVE ? motor : battery;
    int count = kind == WARN_TEMP ? sizeof(thermometer) / sizeof(thermometer[0]) :
        kind == WARN_DRIVE ? sizeof(motor) / sizeof(motor[0]) :
        sizeof(battery) / sizeof(battery[0]);
    lv_draw_line_dsc_t line;
    lv_draw_line_dsc_init(&line);
    line.color = lv_obj_get_style_text_color(obj, 0);
    line.width = 3;
    line.round_start = line.round_end = true;
    for (int i = 0; i < count; ++i) {
        line.p1 = (lv_point_precise_t){area.x1 + 31 + strokes[i][0], area.y1 + strokes[i][1]};
        line.p2 = (lv_point_precise_t){area.x1 + 31 + strokes[i][2], area.y1 + strokes[i][3]};
        lv_draw_line(layer, &line);
    }
    if (kind == WARN_TEMP) {
        lv_draw_rect_dsc_t bulb;
        lv_draw_rect_dsc_init(&bulb);
        bulb.bg_color = line.color;
        bulb.bg_opa = line.opa;
        bulb.radius = LV_RADIUS_CIRCLE;
        lv_area_t bounds = {area.x1 + 46, area.y1 + 26, area.x1 + 58, area.y1 + 38};
        lv_draw_rect(layer, &bulb, &bounds);
    }
    if (kind == WARN_LV) {
        const lv_point_precise_t arrow[] = {
            {area.x1 + 52, area.y1 + 1}, {area.x1 + 52, area.y1 + 9},
            {area.x1 + 48, area.y1 + 5}, {area.x1 + 52, area.y1 + 9},
            {area.x1 + 56, area.y1 + 5}
        };
        for (int i = 0; i < 4; ++i) {
            line.p1 = arrow[i];
            line.p2 = arrow[i + 1];
            lv_draw_line(layer, &line);
        }
    }
}

static lv_obj_t *panel(lv_obj_t *parent, int x, int y, int w, int h,
                       uint32_t color, int radius) {
    lv_obj_t *obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, w, h);
    lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(obj, lv_color_hex(color), 0);
    lv_obj_set_style_radius(obj, radius, 0);
    lv_obj_set_style_border_width(obj, 2, 0);
    lv_obj_set_style_border_color(obj, lv_color_hex(0x555555), 0);
    lv_obj_remove_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
    return obj;
}

static lv_obj_t *text(lv_obj_t *parent, int x, int y, int w,
                      const char *value, const lv_font_t *font, uint32_t color) {
    lv_obj_t *obj = lv_label_create(parent);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_width(obj, w);
    lv_obj_set_style_text_align(obj, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_color(obj, lv_color_hex(color), 0);
    lv_label_set_text(obj, value);
    // A modest uniform text increase keeps the established layout and fonts.
    lv_obj_set_style_transform_scale_x(obj, 282, 0);
    lv_obj_set_style_transform_scale_y(obj, 282, 0);
    lv_obj_set_style_transform_pivot_x(obj, w / 2, 0);
    lv_obj_set_style_transform_pivot_y(obj, font->line_height / 2, 0);
    return obj;
}

static lv_obj_t *card(lv_obj_t *parent, bool right, int y,
                      const char *title, const char *unit) {
    lv_obj_t *obj = panel(parent, right ? 554 : 6, y, 240, 116, 0x171717, 2);
    lv_obj_set_style_bg_grad_color(obj, lv_color_hex(0x4c4c4c), 0);
    lv_obj_set_style_bg_grad_dir(obj, LV_GRAD_DIR_VER, 0);
    int x = right ? 68 : 8;
    text(obj, x, 80, 160, title, &ui_font_orbitron_bold_15, 0xffffff);
    text(obj, right ? 198 : 8, 8, 36, unit, &ui_font_orbitron_bold_20, AMBER);
    return text(obj, x, 17, 160, "0", &ui_font_orbitron_bold_40, AMBER);
}

static lv_obj_t *warning(lv_obj_t *screen, int x, int kind, const char *label) {
    lv_obj_t *obj = lv_obj_create(screen);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, 4);
    lv_obj_set_size(obj, 104, 62);
    lv_obj_remove_flag(obj, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_text_color(obj, lv_color_hex(WARNING_OFF), 0);
    // Fade the composed icon and caption once so stroke joins stay uniform.
    lv_obj_set_style_opa_layered(obj, LV_OPA_20, 0);
    lv_obj_add_event_cb(obj, draw_warning_icon, LV_EVENT_DRAW_MAIN, (void *)(intptr_t)kind);
    lv_obj_t *caption = text(obj, 0, 43, 104, label, &ui_font_orbitron_bold_15, WARNING_OFF);
    lv_obj_remove_local_style_prop(caption, LV_STYLE_TEXT_COLOR, 0);
    return obj;
}

static void warning_style(lv_obj_t *obj, bool active, bool fault) {
    lv_obj_set_style_text_color(obj,
        lv_color_hex(active ? (fault ? WARNING_RED : WARNING_ON) : WARNING_OFF), 0);
    lv_obj_set_style_opa_layered(obj, active && fault ? LV_OPA_COVER : LV_OPA_20, 0);
}

static const char *inverter_fault_description(float code) {
    // HV-500 / DTI CAN manual V2.5 fault codes. Keep unknown codes explicit
    // rather than guessing the meaning of firmware-specific extensions.
    static const char *const descriptions[] = {
        "NO FAULT", "HV INPUT VOLTAGE TOO HIGH", "HV INPUT VOLTAGE TOO LOW",
        "GATE DRIVER FAULT", "MOTOR PHASE OVERCURRENT", "INVERTER OVERHEAT",
        "MOTOR OVERHEAT", "POSITION SENSOR WIRING FAULT",
        "POSITION SENSOR READ ERROR", "CAN COMMAND OUT OF RANGE"
    };
    if (code >= 0 && code < (float)(sizeof(descriptions) / sizeof(descriptions[0])) &&
        code == floorf(code)) return descriptions[(int)code];
    return "UNKNOWN INVERTER FAULT";
}

static bool low_warning(float value, bool active, float on, float clear) {
    return isfinite(value) && value >= 0 && value <= (active ? clear : on);
}

static bool hot_warning(float value, bool active, float on) {
    return isfinite(value) && value >= (active ? on - TEMP_HYSTERESIS_C : on);
}

static void update_warnings(void) {
    motor_hot = hot_warning(fmaxf(dbc_api.inv1_temperatures.inv1_actual_tempmotor,
        dbc_api.inv2_temperatures.inv2_actual_tempmotor), motor_hot, MOTOR_WARN_C);
    inverter_hot = hot_warning(fmaxf(dbc_api.inv1_temperatures.inv1_actual_tempcontroller,
        dbc_api.inv2_temperatures.inv2_actual_tempcontroller), inverter_hot, INVERTER_WARN_C);
    battery_hot = hot_warning(dbc_api.master_msc_id_3.overall_maximum_temperature,
        battery_hot, BATTERY_WARN_C);
    bool thermal_limit = dbc_api.inv1_misc.inv1_motor_temp_limit == 1 ||
        dbc_api.inv1_misc.inv1_igbt_temp_limit == 1 ||
        dbc_api.inv1_misc.inv1_capacitor_temp_limit == 1 ||
        dbc_api.inv1_misc.inv1_motor_accel_limit == 1 ||
        dbc_api.inv1_misc.inv1_igbt_accel_limit == 1 ||
        dbc_api.inv2_misc.inv2_motor_temp_limit == 1 ||
        dbc_api.inv2_misc.inv2_igbt_temp_limit == 1 ||
        dbc_api.inv2_misc.inv2_capacitor_temp_limit == 1 ||
        dbc_api.inv2_misc.inv2_motor_accel_limit == 1 ||
        dbc_api.inv2_misc.inv2_igbt_accel_limit == 1;
    bool temp = motor_hot || inverter_hot || battery_hot || thermal_limit;
    float code1 = dbc_api.inv1_temperatures.inv1_actual_faultcode;
    float code2 = dbc_api.inv2_temperatures.inv2_actual_faultcode;
    bool fault1 = isfinite(code1) && code1 > 0;
    bool fault2 = isfinite(code2) && code2 > 0;
    bool drive = fault1 || fault2;
    float soc = dbc_api.master_soc_accumulator.soc_float;
    soc_low = soc <= 100 && low_warning(soc, soc_low, LOW_SOC_ON_PERCENT, LOW_SOC_CLEAR_PERCENT);
    lv_low = low_warning(ui_get_lv_voltage(), lv_low, LOW_LV_ON_V, LOW_LV_CLEAR_V);
    warning_style(objects.gauge_temp_warning, temp, false);
    warning_style(objects.gauge_drive_warning, drive, true);
    warning_style(objects.gauge_soc_warning, soc_low, false);
    warning_style(objects.gauge_lv_warning, lv_low, false);

    char fault_message[192];
    if (fault1 && fault2) {
        snprintf(fault_message, sizeof(fault_message), "INV1 ERROR %.0f: %s | INV2 ERROR %.0f: %s",
            (double)code1, inverter_fault_description(code1),
            (double)code2, inverter_fault_description(code2));
    } else if (drive) {
        float code = fault1 ? code1 : code2;
        snprintf(fault_message, sizeof(fault_message), "INV%d ERROR %.0f: %s",
            fault1 ? 1 : 2, (double)code, inverter_fault_description(code));
    }
    const char *message = drive ? fault_message : battery_hot ? "BATTERY TEMPERATURE HIGH" :
        motor_hot ? "MOTOR TEMPERATURE HIGH" :
        inverter_hot ? "INVERTER TEMPERATURE HIGH" :
        thermal_limit ? "DRIVE TEMPERATURE LIMIT" :
        lv_low ? "LOW LV BATTERY VOLTAGE" : soc_low ? "LOW ACCUMULATOR SOC" : "";
    lv_label_set_text(objects.gauge_warning_message, message);
    uint32_t color = drive ? WARNING_RED : WARNING_ON;
    lv_opa_t opacity = drive ? LV_OPA_COVER : LV_OPA_20;
    lv_obj_set_style_border_color(warning_banner, lv_color_hex(color), 0);
    lv_obj_set_style_border_opa(warning_banner, opacity, 0);
    lv_obj_set_style_bg_opa(warning_banner, opacity, 0);
    lv_obj_set_style_text_color(objects.gauge_warning_message, lv_color_hex(color), 0);
    lv_obj_set_style_text_opa(objects.gauge_warning_message, opacity, 0);
    if (*message) lv_obj_remove_flag(warning_banner, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(warning_banner, LV_OBJ_FLAG_HIDDEN);
}

static lv_obj_t *pedal_bar(lv_obj_t *parent, int y) {
    lv_obj_t *bar = lv_bar_create(parent);
    lv_obj_remove_style_all(bar);
    lv_obj_set_pos(bar, 68, y);
    lv_obj_set_size(bar, 160, 18);
    lv_bar_set_range(bar, 0, 100);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar, lv_color_hex(0x111111), LV_PART_MAIN);
    lv_obj_set_style_border_width(bar, 1, LV_PART_MAIN);
    lv_obj_set_style_border_color(bar, lv_color_hex(0x777777), LV_PART_MAIN);
    lv_obj_set_style_radius(bar, 2, LV_PART_MAIN);
    lv_obj_set_style_pad_all(bar, 2, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(bar, lv_color_hex(AMBER), LV_PART_INDICATOR);
    lv_obj_set_style_bg_grad_color(bar, lv_color_hex(0xba8e0c), LV_PART_INDICATOR);
    lv_obj_set_style_bg_grad_dir(bar, LV_GRAD_DIR_VER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, 1, LV_PART_INDICATOR);
    return bar;
}

static lv_point_precise_t polar(float radius, float degrees) {
    float angle = degrees * 3.14159265f / 180.0f;
    return (lv_point_precise_t){236 + radius * cosf(angle), 236 + radius * sinf(angle)};
}

void create_screen_driver_gauge() {
    lv_obj_t *screen = panel(NULL, 0, 0, 800, 480, 0x050505, 0);
    objects.driver_gauge = screen;
    lv_obj_set_style_border_width(screen, 0, 0);

    objects.gauge_motor_temp = card(screen, false, 70, "MOTOR TEMP", "°C");
    objects.gauge_inv_temp = card(screen, false, 202, "INV TEMP", "°C");
    objects.gauge_bat_temp = card(screen, false, 334, "BAT TEMP", "°C");
    objects.gauge_lv = card(screen, true, 70, "LV", "");
    objects.gauge_soc = card(screen, true, 202, "SOC", "%");
    lv_obj_t *pedals = panel(screen, 554, 334, 240, 116, 0x171717, 2);
    lv_obj_set_style_bg_grad_color(pedals, lv_color_hex(0x4c4c4c), 0);
    lv_obj_set_style_bg_grad_dir(pedals, LV_GRAD_DIR_VER, 0);
    objects.gauge_apps_label = text(pedals, 68, 6, 160, "APPS 0%", &ui_font_orbitron_bold_15, AMBER);
    objects.gauge_apps_bar = pedal_bar(pedals, 32);
    objects.gauge_brake_label = text(pedals, 68, 62, 160, "BRAKE 0%", &ui_font_orbitron_bold_15, AMBER);
    objects.gauge_brake_bar = pedal_bar(pedals, 86);

    lv_obj_t *dial = panel(screen, 164, 4, 472, 472, 0x444444, LV_RADIUS_CIRCLE);
    objects.gauge_dial = dial;
    // Draw the bezel as a separate ring so borders do not offset the dial content.
    lv_obj_set_style_border_width(dial, 0, 0);
    lv_obj_t *face = panel(dial, 7, 7, 458, 458, 0x161616, LV_RADIUS_CIRCLE);
    lv_obj_set_style_border_width(face, 0, 0);
    lv_obj_set_style_bg_grad_color(face, lv_color_hex(0x36332e), 0);
    lv_obj_set_style_bg_grad_dir(face, LV_GRAD_DIR_VER, 0);
    lv_obj_t *rim = panel(dial, 19, 19, 434, 434, 0x2b2824, LV_RADIUS_CIRCLE);
    lv_obj_set_style_border_color(rim, lv_color_hex(0xb5b5b5), 0);

    lv_obj_t *red_arc = lv_arc_create(dial);
    lv_obj_remove_style_all(red_arc);
    lv_obj_set_pos(red_arc, 24, 24);
    lv_obj_set_size(red_arc, 424, 424);
    lv_arc_set_bg_angles(red_arc, 337, 405);
    lv_obj_set_style_arc_color(red_arc, lv_color_hex(0xe51b23), LV_PART_MAIN);
    lv_obj_set_style_arc_width(red_arc, 56, LV_PART_MAIN);
    lv_obj_set_style_arc_rounded(red_arc, false, LV_PART_MAIN);
    lv_obj_remove_flag(red_arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_style(red_arc, NULL, LV_PART_KNOB);

    for (int i = 0; i <= 40; ++i) {
        float angle = 135.0f + i * 6.75f;
        ticks[i][0] = polar(212, angle);
        ticks[i][1] = polar(i % 4 == 0 ? 197 : 205, angle);
        lv_obj_t *line = lv_line_create(dial);
        lv_line_set_points(line, ticks[i], 2);
        lv_obj_set_style_line_color(line, lv_color_hex(0xdddddd), 0);
        lv_obj_set_style_line_width(line, i % 4 == 0 ? 4 : 1, 0);
        if (i % 4 == 0) {
            lv_point_precise_t p = polar(177, angle);
            lv_obj_t *label = text(dial, (int)p.x - 27, (int)p.y - 17, 54,
                                   "", &ui_font_orbitron_bold_30, AMBER);
            lv_label_set_text_fmt(label, "%d", i / 2);
        }
    }
    lv_obj_t *hub = panel(dial, 80, 80, 312, 312, 0x030303, LV_RADIUS_CIRCLE);
    lv_obj_set_style_border_width(hub, 8, 0);
    lv_obj_set_style_border_color(hub, lv_color_hex(0x111111), 0);

    // Principal LART logo, trimmed to its alpha bounds for a larger visible mark.
    lv_obj_t *logo = lv_image_create(dial);
    objects.gauge_logo = logo;
    lv_obj_remove_style_all(logo);
    lv_image_set_src(logo, &img_lart_logo_principal);
    lv_obj_set_pos(logo, 137, 133);

    needle = lv_line_create(dial);
    objects.gauge_needle = needle;
    lv_obj_set_style_line_color(needle, lv_color_hex(0xff272e), 0);
    lv_obj_set_style_line_width(needle, 7, 0);
    lv_obj_set_style_line_rounded(needle, true, 0);
    panel(dial, 224, 224, 24, 24, 0xb90b12, LV_RADIUS_CIRCLE);
    // Digital inset sits above the needle, like the reference cluster.
    lv_obj_t *inset = panel(dial, 130, 188, 212, 96, 0x161616, 4);
    objects.gauge_speed = text(inset, 0, 4, 208, "0", &ui_font_orbitron_bold_50, AMBER);
    text(inset, 0, 67, 208, "km/h", &ui_font_orbitron_bold_15, 0xffffff);
    text(dial, 173, 423, 126, "RPM x 1000", &ui_font_orbitron_15, 0xaaaaaa);
    ready = text(dial, 116, 326, 240, "NOT READY", &ui_font_orbitron_bold_20, AMBER);
    motor_hot = inverter_hot = battery_hot = soc_low = lv_low = false;
    objects.gauge_temp_warning = warning(screen, 8, WARN_TEMP, "TEMP");
    objects.gauge_drive_warning = warning(screen, 124, WARN_DRIVE, "DRIVE");
    objects.gauge_soc_warning = warning(screen, 572, WARN_SOC, "LOW SOC");
    objects.gauge_lv_warning = warning(screen, 688, WARN_LV, "LOW LV");
    warning_banner = panel(screen, 6, 452, 788, 28, 0x050505, 2);
    objects.gauge_warning_message = text(warning_banner, 0, 2, 784, "",
        &ui_font_orbitron_bold_15, WARNING_ON);
    lv_obj_set_height(objects.gauge_warning_message, 22);
    lv_obj_set_style_transform_scale_x(objects.gauge_warning_message, 256, 0);
    lv_obj_set_style_transform_scale_y(objects.gauge_warning_message, 256, 0);
    lv_label_set_long_mode(objects.gauge_warning_message, LV_LABEL_LONG_SCROLL_CIRCULAR);
    tick_screen_driver_gauge();
}

static void set_number(lv_obj_t *label, float value) {
    char buffer[32];
    snprintf(buffer, sizeof(buffer), "%.0f", (double)value);
    lv_label_set_text(label, buffer);
}

void tick_screen_driver_gauge() {
    ui_update_telemetry_vars(NULL);
    ui_update_network_status();
    update_driver_precharge_overlay();
    float rpm = dbc_api.inv1_erpm_duty_voltage.inv1_actual_erpm / 4.0f;
    if (!isfinite(rpm)) rpm = 0;
    set_number(objects.gauge_speed, ui_get_speed());
    float dial_rpm = fminf(fabsf(rpm), DIAL_MAX_RPM);
    needle_points[0] = polar(0, 0);
    needle_points[1] = polar(190, 135 + 270 * dial_rpm / DIAL_MAX_RPM);
    lv_line_set_points(needle, needle_points, 2);
    set_number(objects.gauge_motor_temp, dbc_api.inv1_temperatures.inv1_actual_tempmotor);
    set_number(objects.gauge_inv_temp, dbc_api.inv1_temperatures.inv1_actual_tempcontroller);
    set_number(objects.gauge_bat_temp, dbc_api.master_msc_id_3.overall_maximum_temperature);
    lv_label_set_text(objects.gauge_lv, ui_get_lv_str());
    set_number(objects.gauge_soc, dbc_api.master_soc_accumulator.soc_float);
    int apps = ui_get_apps_percentage();
    int brake = ui_get_brake_percentage();
    lv_bar_set_value(objects.gauge_apps_bar, apps, LV_ANIM_OFF);
    lv_bar_set_value(objects.gauge_brake_bar, brake, LV_ANIM_OFF);
    lv_label_set_text_fmt(objects.gauge_apps_label, "APPS %d%%", apps);
    lv_label_set_text_fmt(objects.gauge_brake_label, "BRAKE %d%%", brake);
    bool is_ready = dbc_api.vcu_states.vcu_state == 6 || dbc_api.vcu_states.vcu_state == 7;
    lv_label_set_text(ready, is_ready ? "READY" : "NOT READY");
    lv_obj_set_style_text_color(ready, lv_color_hex(is_ready ? 0x3fff00 : AMBER), 0);
    update_warnings();
}
