#include "ui.h"
#include "screens.h"
#include "fonts.h"
#include "vars.h"
#include "eez-flow.h"

#include <cstdint>
#include <cstdio>

namespace {

enum class SpeedPullState {
    Ready,
    Running,
    Complete
};

SpeedPullState speed_pull_state = SpeedPullState::Ready;
std::uint32_t speed_pull_start_ms = 0;
std::uint32_t speed_pull_result_ms = 0;
bool speed_pull_has_result = false;

void set_speed_pull_labels(const char *time_text, const char *status_text) {
    if (objects.laptime_label) {
        lv_obj_set_pos(objects.laptime_label, 6, 8);
        lv_obj_set_style_text_font(objects.laptime_label, &ui_font_orbitron_bold_30, LV_PART_MAIN | LV_STATE_DEFAULT);
        lv_label_set_text(objects.laptime_label, time_text);
    }
    if (objects.lastlap_label) {
        lv_obj_set_pos(objects.lastlap_label, 220, 8);
        lv_obj_set_style_text_font(objects.lastlap_label, &ui_font_orbitron_bold_30, LV_PART_MAIN | LV_STATE_DEFAULT);
        lv_label_set_text(objects.lastlap_label, status_text);
    }
    if (objects.laptime_label_1) {
        lv_obj_set_pos(objects.laptime_label_1, 6, 8);
        lv_obj_set_style_text_font(objects.laptime_label_1, &ui_font_orbitron_bold_30, LV_PART_MAIN | LV_STATE_DEFAULT);
        lv_label_set_text(objects.laptime_label_1, time_text);
    }
    if (objects.lastlap_label_1) {
        lv_obj_set_pos(objects.lastlap_label_1, 205, 8);
        lv_obj_set_style_text_font(objects.lastlap_label_1, &ui_font_orbitron_bold_30, LV_PART_MAIN | LV_STATE_DEFAULT);
        lv_label_set_text(objects.lastlap_label_1, status_text);
    }

    if (objects.lap_times_container_1) lv_obj_set_width(objects.lap_times_container_1, 370);
    if (objects.obj0) lv_obj_add_flag(objects.obj0, LV_OBJ_FLAG_HIDDEN);
    if (objects.obj1) lv_obj_add_flag(objects.obj1, LV_OBJ_FLAG_HIDDEN);
    if (objects.obj4) lv_obj_add_flag(objects.obj4, LV_OBJ_FLAG_HIDDEN);
    if (objects.obj5) lv_obj_add_flag(objects.obj5, LV_OBJ_FLAG_HIDDEN);
}

} // namespace

extern "C" void ui_set_screen_var(int screen_id) {
    eez::flow::setGlobalVariable(
        FLOW_GLOBAL_VARIABLE_SCREEN_CHANGER_VAR,
        eez::IntegerValue(screen_id)
    );
}

extern "C" void ui_update_speed_pull_display(float speed_kph) {
    constexpr float start_speed_kph = 0.5f;
    const std::uint32_t now_ms = lv_tick_get();

    if (speed_pull_state == SpeedPullState::Ready && speed_kph > start_speed_kph) {
        speed_pull_start_ms = now_ms;
        speed_pull_result_ms = 0;
        speed_pull_has_result = false;
        speed_pull_state = SpeedPullState::Running;
    } else if (speed_pull_state == SpeedPullState::Running) {
        if (speed_kph >= 60.0f) {
            speed_pull_result_ms = now_ms - speed_pull_start_ms;
            speed_pull_has_result = true;
            speed_pull_state = SpeedPullState::Complete;
        } else if (speed_kph <= start_speed_kph) {
            speed_pull_result_ms = 0;
            speed_pull_has_result = false;
            speed_pull_state = SpeedPullState::Ready;
        }
    } else if (speed_pull_state == SpeedPullState::Complete && speed_kph <= start_speed_kph) {
        speed_pull_state = SpeedPullState::Ready;
    }

    const std::uint32_t elapsed_ms = speed_pull_state == SpeedPullState::Running
        ? now_ms - speed_pull_start_ms
        : speed_pull_result_ms;
    char time_text[24];
    std::snprintf(
        time_text,
        sizeof(time_text),
        "%lu.%03lu s",
        static_cast<unsigned long>(elapsed_ms / 1000),
        static_cast<unsigned long>(elapsed_ms % 1000)
    );

    if (speed_pull_state == SpeedPullState::Running) {
        set_speed_pull_labels(time_text, "PULL");
    } else if (speed_pull_state == SpeedPullState::Complete) {
        set_speed_pull_labels(time_text, "LOGGED");
    } else {
        set_speed_pull_labels(speed_pull_has_result ? time_text : "--.--- s", "READY");
    }

    char speed_text[16];
    std::snprintf(speed_text, sizeof(speed_text), "%.0f", static_cast<double>(speed_kph));
    if (objects.speed_label) lv_label_set_text(objects.speed_label, speed_text);
    if (objects.speed_label_1) lv_label_set_text(objects.speed_label_1, speed_text);
}
