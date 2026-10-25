"""Check topic selection without starting DDS or writing a bag."""

import re
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lart_bringup.bag_recorder import BagRecorderNode


def test_records_all_topics_except_zed_including_hidden_topics(tmp_path):
    recorder = SimpleNamespace(
        _bag_dir=tmp_path / 'bags',
        _record_regex='/data/.*|/pwt/.*|/can/(?!frames$).*|/imu/.*',
        _split_s=0,
        get_logger=Mock(),
    )
    with patch('lart_bringup.bag_recorder.subprocess.Popen') as popen:
        assert BagRecorderNode._start_recording(recorder)

    command = popen.call_args.args[0]
    assert command[:3] == ['ros2', 'bag', 'record']
    assert command[command.index('-s') + 1] == 'mcap'
    assert '--all-topics' in command
    assert '--include-hidden-topics' in command
    assert '-e' not in command
    assert '--exclude-topics' not in command
    excluded = command[command.index('--exclude-regex') + 1]
    assert re.search(excluded, '/zed/zed_node/rgb/image_rect_color')
    assert re.search(excluded, '/zed/point_cloud')
    assert not re.search(excluded, '/can/frames')
    assert not re.search(excluded, '/data/speed')
    assert not re.search(excluded, '/zed_other/image')
    assert not re.search(excluded, '/other/zed/image')
    assert '--no-discovery' not in command
    assert recorder._proc is popen.return_value
