"""Family generator registry: `FAMILIES[name].generate(seed) -> Golden`.

Hard-tier composite families (multi-rail boards, `TIER = "hard"` in the module) are registered
too; `V1_FAMILIES` / `HARD_FAMILIES` split the registry so v1-style generation can skip them.
"""
from __future__ import annotations

from types import ModuleType

from pcbenv.families import (divider_adc, ldo_reg, led_driver, mcu_i2c, nmos_switch, npn_switch, opamp_inv,
                             opamp_noninv, rc_lowpass, sys_analog_frontend, sys_clocked_mcu, sys_motor_ctrl,
                             sys_sensor_node, xtal_osc)

FAMILIES: dict[str, ModuleType] = {m.FAMILY: m for m in (
    ldo_reg, led_driver, npn_switch, nmos_switch, opamp_noninv, opamp_inv, rc_lowpass, divider_adc, mcu_i2c,
    xtal_osc, sys_sensor_node, sys_motor_ctrl, sys_clocked_mcu, sys_analog_frontend,
)}


def tier(name: str) -> str:
    return getattr(FAMILIES[name], "TIER", "v1")


V1_FAMILIES: list[str] = sorted(n for n in FAMILIES if tier(n) != "hard")
HARD_FAMILIES: list[str] = sorted(n for n in FAMILIES if tier(n) == "hard")
