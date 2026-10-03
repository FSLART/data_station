#!/usr/bin/env python3
"""Temperature-controlled fan PWM on a Raspberry Pi 5 GPIO (default GPIO12 -> MOSFET -> fan).

  python3 scripts/fan_pwm.py                 # run (Ctrl-C = fan off)
  python3 scripts/fan_pwm.py --selftest      # check the duty curve, no hardware needed

Curve: off below --off-temp, jumps to --min-duty at --on-temp, linear to 100 % at --max-temp.
The gap between --off-temp and --on-temp is the hysteresis (no on/off flapping).

Needs python3-gpiod >= 2 (already used by input_handler). Run as a user in the gpio group.
"""
import argparse
import os
import signal
import time

THERMAL = '/sys/class/thermal/thermal_zone0/temp'   # CPU temp, millidegrees C


def duty_for(temp, running, off_temp, on_temp, max_temp, min_duty):
    """Duty 0..1 for a CPU temperature. `running` = fan was on in the previous step."""
    if temp >= max_temp:
        return 1.0
    if temp >= on_temp or (running and temp > off_temp):
        span = max(max_temp - on_temp, 0.1)
        return min(1.0, max(min_duty, min_duty + (1 - min_duty) * (temp - on_temp) / span))
    return 0.0


def selftest():
    p = dict(off_temp=45, on_temp=50, max_temp=70, min_duty=0.3)
    assert duty_for(40, False, **p) == 0.0           # cool: off
    assert duty_for(48, False, **p) == 0.0           # in hysteresis band, was off: stays off
    assert duty_for(48, True, **p) == 0.3            # in hysteresis band, was on: stays on (min duty)
    assert duty_for(50, False, **p) == 0.3           # reaches on_temp: min duty
    assert abs(duty_for(60, True, **p) - 0.65) < 1e-9  # halfway: 0.3 + 0.7 * 0.5
    assert duty_for(75, True, **p) == 1.0            # above max: full
    assert duty_for(44, True, **p) == 0.0            # below off_temp: off again
    print('fan_pwm selftest ok')


def read_temp():
    with open(THERMAL) as f:
        return int(f.read()) / 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pin', type=int, default=12)
    ap.add_argument('--freq', type=float, default=100.0, help='PWM Hz (software PWM, keep <= ~200)')
    ap.add_argument('--off-temp', type=float, default=45.0)
    ap.add_argument('--on-temp', type=float, default=50.0)
    ap.add_argument('--max-temp', type=float, default=70.0)
    ap.add_argument('--min-duty', type=float, default=0.3, help='lowest duty at which the fan still spins')
    ap.add_argument('--poll', type=float, default=2.0, help='seconds between temperature reads')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    import gpiod
    from gpiod.line import Direction, Value

    chip = next(p for p in ('/dev/gpiochip4', '/dev/gpiochip0') if os.path.exists(p))
    req = gpiod.request_lines(
        chip, consumer='fan_pwm',
        config={a.pin: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)})

    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    period = 1.0 / a.freq
    duty, running, next_poll = 0.0, False, 0.0
    try:
        while not stop:
            now = time.monotonic()
            if now >= next_poll:
                temp = read_temp()
                new = duty_for(temp, running, a.off_temp, a.on_temp, a.max_temp, a.min_duty)
                if running is False and new > 0:          # kick-start a stopped fan
                    req.set_value(a.pin, Value.ACTIVE)
                    time.sleep(0.5)
                duty, running, next_poll = new, new > 0, now + a.poll
                print(f'{temp:5.1f} C -> fan {duty * 100:3.0f} %', flush=True)
            if duty <= 0.0 or duty >= 1.0:                # no switching needed
                req.set_value(a.pin, Value.ACTIVE if duty else Value.INACTIVE)
                time.sleep(min(0.25, a.poll))
            else:                                         # ponytail: software PWM, ~100 us jitter; use dtoverlay=pwm,pin=12,func=4 for hardware PWM if the fan hums
                req.set_value(a.pin, Value.ACTIVE)
                time.sleep(period * duty)
                req.set_value(a.pin, Value.INACTIVE)
                time.sleep(period * (1 - duty))
    finally:
        req.set_value(a.pin, Value.INACTIVE)               # always leave the fan off
        req.release()


if __name__ == '__main__':
    main()
