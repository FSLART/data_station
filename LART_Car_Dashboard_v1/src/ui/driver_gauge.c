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

static lv_obj_t *needle;
static lv_obj_t *ready;
static lv_point_precise_t needle_points[2];
static lv_point_precise_t ticks[41][2];

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
    return obj;
}

static lv_obj_t *card(lv_obj_t *parent, bool right, int y,
                      const char *title, const char *unit) {
    lv_obj_t *obj = panel(parent, right ? 554 : 6, y, 240, 108, 0x171717, 2);
    lv_obj_set_style_bg_grad_color(obj, lv_color_hex(0x4c4c4c), 0);
    lv_obj_set_style_bg_grad_dir(obj, LV_GRAD_DIR_VER, 0);
    int x = right ? 68 : 8;
    text(obj, x, 73, 160, title, &ui_font_orbitron_bold_15, 0xffffff);
    text(obj, right ? 209 : 8, 10, 25, unit, &ui_font_orbitron_15, AMBER);
    return text(obj, x, 17, 160, "0", &ui_font_orbitron_bold_40, AMBER);
}

static lv_obj_t *pedal_bar(lv_obj_t *parent, int y) {
    lv_obj_t *bar = lv_bar_create(parent);
    lv_obj_remove_style_all(bar);
    lv_obj_set_pos(bar, 68, y);
    lv_obj_set_size(bar, 160, 14);
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
    return (lv_point_precise_t){216 + radius * cosf(angle), 216 + radius * sinf(angle)};
}

void create_screen_driver_gauge() {
    lv_obj_t *screen = panel(NULL, 0, 0, 800, 480, 0x050505, 0);
    objects.driver_gauge = screen;
    lv_obj_set_style_border_width(screen, 0, 0);
    ready = text(screen, 250, 7, 300, "NOT READY", &ui_font_orbitron_bold_20, AMBER);

    objects.gauge_motor_temp = card(screen, false, 76, "MOTOR TEMP", "°C");
    objects.gauge_inv_temp = card(screen, false, 208, "INV TEMP", "°C");
    objects.gauge_bat_temp = card(screen, false, 340, "BAT TEMP", "°C");
    objects.gauge_lv = card(screen, true, 76, "LV", "");
    objects.gauge_soc = card(screen, true, 208, "SOC", "%");
    lv_obj_t *pedals = panel(screen, 554, 340, 240, 108, 0x171717, 2);
    lv_obj_set_style_bg_grad_color(pedals, lv_color_hex(0x4c4c4c), 0);
    lv_obj_set_style_bg_grad_dir(pedals, LV_GRAD_DIR_VER, 0);
    objects.gauge_apps_label = text(pedals, 68, 6, 160, "APPS 0%", &ui_font_orbitron_bold_15, AMBER);
    objects.gauge_apps_bar = pedal_bar(pedals, 30);
    objects.gauge_brake_label = text(pedals, 68, 56, 160, "BRAKE 0%", &ui_font_orbitron_bold_15, AMBER);
    objects.gauge_brake_bar = pedal_bar(pedals, 80);

    lv_obj_t *dial = panel(screen, 184, 24, 432, 432, 0x444444, LV_RADIUS_CIRCLE);
    objects.gauge_dial = dial;
    // Draw the bezel as a separate ring so borders do not offset the dial content.
    lv_obj_set_style_border_width(dial, 0, 0);
    lv_obj_t *face = panel(dial, 7, 7, 418, 418, 0x161616, LV_RADIUS_CIRCLE);
    lv_obj_set_style_border_width(face, 0, 0);
    lv_obj_set_style_bg_grad_color(face, lv_color_hex(0x36332e), 0);
    lv_obj_set_style_bg_grad_dir(face, LV_GRAD_DIR_VER, 0);
    lv_obj_t *rim = panel(dial, 19, 19, 394, 394, 0x2b2824, LV_RADIUS_CIRCLE);
    lv_obj_set_style_border_color(rim, lv_color_hex(0xb5b5b5), 0);

    lv_obj_t *red_arc = lv_arc_create(dial);
    lv_obj_remove_style_all(red_arc);
    lv_obj_set_pos(red_arc, 24, 24);
    lv_obj_set_size(red_arc, 384, 384);
    lv_arc_set_bg_angles(red_arc, 337, 405);
    lv_obj_set_style_arc_color(red_arc, lv_color_hex(0xe51b23), LV_PART_MAIN);
    lv_obj_set_style_arc_width(red_arc, 52, LV_PART_MAIN);
    lv_obj_set_style_arc_rounded(red_arc, false, LV_PART_MAIN);
    lv_obj_remove_flag(red_arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_style(red_arc, NULL, LV_PART_KNOB);

    for (int i = 0; i <= 40; ++i) {
        float angle = 135.0f + i * 6.75f;
        ticks[i][0] = polar(192, angle);
        ticks[i][1] = polar(i % 4 == 0 ? 177 : 185, angle);
        lv_obj_t *line = lv_line_create(dial);
        lv_line_set_points(line, ticks[i], 2);
        lv_obj_set_style_line_color(line, lv_color_hex(0xdddddd), 0);
        lv_obj_set_style_line_width(line, i % 4 == 0 ? 3 : 1, 0);
        if (i % 4 == 0) {
            lv_point_precise_t p = polar(157, angle);
            lv_obj_t *label = text(dial, (int)p.x - 27, (int)p.y - 17, 54,
                                   "", &ui_font_orbitron_bold_30, AMBER);
            lv_label_set_text_fmt(label, "%d", i / 2);
        }
    }
    lv_obj_t *hub = panel(dial, 80, 80, 272, 272, 0x030303, LV_RADIUS_CIRCLE);
    lv_obj_set_style_border_width(hub, 8, 0);
    lv_obj_set_style_border_color(hub, lv_color_hex(0x111111), 0);

    // Principal LART logo, trimmed to its alpha bounds for a larger visible mark.
    lv_obj_t *logo = lv_image_create(dial);
    objects.gauge_logo = logo;
    lv_obj_remove_style_all(logo);
    lv_image_set_src(logo, &img_lart_logo_principal);
    lv_obj_set_pos(logo, 115, 114);

    needle = lv_line_create(dial);
    objects.gauge_needle = needle;
    lv_obj_set_style_line_color(needle, lv_color_hex(0xff272e), 0);
    lv_obj_set_style_line_width(needle, 6, 0);
    lv_obj_set_style_line_rounded(needle, true, 0);
    panel(dial, 204, 204, 24, 24, 0xb90b12, LV_RADIUS_CIRCLE);
    // Digital inset sits above the needle, like the reference cluster.
    lv_obj_t *inset = panel(dial, 116, 172, 200, 88, 0x161616, 4);
    objects.gauge_speed = text(inset, 0, 2, 196, "0", &ui_font_orbitron_bold_50, AMBER);
    text(inset, 0, 61, 196, "km/h", &ui_font_orbitron_bold_15, 0xffffff);
    text(dial, 153, 383, 126, "RPM x 1000", &ui_font_orbitron_15, 0xaaaaaa);
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
    needle_points[1] = polar(170, 135 + 270 * dial_rpm / DIAL_MAX_RPM);
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
}
