from pathlib import Path
import subprocess


def test_ros_cpp_and_display_c_share_precharge_field_layout(tmp_path):
    ui_dir = Path(__file__).resolve().parents[1] / "LART_Car_Dashboard_v1/src/ui"
    source = '''
#include <stddef.h>
#include <stdio.h>
#include "dbc_api.h"
int main(void) {
    printf("%zu %zu\\n", sizeof(DbcApi),
           offsetof(DbcApi, master_precharge_id_1.precharge_state));
    return 0;
}
'''
    layouts = []
    for compiler, extension in [("cc", "c"), ("c++", "cpp")]:
        path = tmp_path / f"layout.{extension}"
        path.write_text(source)
        binary = tmp_path / f"layout-{extension}"
        subprocess.run([compiler, "-I", str(ui_dir), str(path), "-o", str(binary)], check=True)
        layouts.append(subprocess.check_output([str(binary)], text=True).strip())
    assert layouts[0] == layouts[1], f"C display layout {layouts[0]} differs from C++ ROS layout {layouts[1]}"
