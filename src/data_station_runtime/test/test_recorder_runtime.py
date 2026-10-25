"""Exercise combined runtime requests against the real recorder state machine."""

from unittest.mock import Mock

from data_station_runtime.recording_trigger import RecordingTriggers
from lart_bringup.trigger_state import State, TriggerStateMachine


def setup_recorder():
    calls = Mock()
    calls.start.return_value = True
    state = TriggerStateMachine(calls.start, calls.stop, calls.arm, calls.cancel)
    return RecordingTriggers(state.on_trigger), state, calls


def test_no_trigger_is_emitted_before_receiving_a_request():
    callback = Mock()
    triggers = RecordingTriggers(callback)
    assert not triggers.active
    callback.assert_not_called()


def test_precharge_request_drives_recording():
    triggers, state, calls = setup_recorder()
    triggers.on_precharge(True)
    assert state.state is State.RECORDING
    triggers.on_precharge(False)
    assert state.state is State.GRACE
    calls.arm.assert_called_once()
    calls.stop.assert_not_called()


def test_jetson_ready_to_driving_keeps_same_recording():
    triggers, state, calls = setup_recorder()
    triggers.on_jetson_state(2)
    triggers.on_jetson_state(3)
    assert triggers.active
    assert state.state is State.RECORDING
    calls.start.assert_called_once()
    calls.arm.assert_not_called()
    triggers.on_jetson_state(1)
    assert state.state is State.GRACE


def test_both_requests_must_clear_before_grace_and_resume_keeps_bag():
    triggers, state, calls = setup_recorder()
    triggers.on_precharge(True)
    triggers.on_jetson_state(2)
    triggers.on_precharge(False)
    assert state.state is State.RECORDING
    triggers.on_jetson_state(1)
    assert state.state is State.GRACE
    triggers.on_precharge(True)
    assert state.state is State.RECORDING
    state.on_grace_expired()
    calls.start.assert_called_once()
    calls.cancel.assert_called_once()
    calls.stop.assert_not_called()


def test_precharge_publisher_silence_does_not_stop_recording():
    triggers, state, calls = setup_recorder()
    triggers.on_precharge(True)
    triggers.on_jetson_state(1)
    assert state.state is State.RECORDING
    assert triggers.active
    calls.arm.assert_not_called()


def test_autonomous_publisher_silence_does_not_stop_recording():
    triggers, state, calls = setup_recorder()
    triggers.on_jetson_state(2)
    triggers.on_precharge(False)
    assert state.state is State.RECORDING
    assert triggers.active
    calls.arm.assert_not_called()


def test_explicit_inactive_requests_finalize_after_grace():
    triggers, state, calls = setup_recorder()
    triggers.on_jetson_state(2)
    triggers.on_jetson_state(4)
    assert state.state is State.GRACE
    state.on_grace_expired()
    assert state.state is State.IDLE
    calls.stop.assert_called_once()


def test_recording_failure_retries_on_next_active_sample():
    triggers, state, calls = setup_recorder()
    calls.start.side_effect = [False, True]
    triggers.on_precharge(True)
    assert state.state is State.IDLE
    triggers.on_precharge(True)
    assert state.state is State.RECORDING
    assert calls.start.call_count == 2
