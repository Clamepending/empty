"""Family generator registry: `FAMILIES[name].generate(seed) -> Golden`."""
from __future__ import annotations

from types import ModuleType

from pcbenv.families import (divider_adc, ldo_reg, led_driver, mcu_i2c, nmos_switch, npn_switch, opamp_inv,
                             opamp_noninv, rc_lowpass, xtal_osc)

FAMILIES: dict[str, ModuleType] = {m.FAMILY: m for m in (
    ldo_reg, led_driver, npn_switch, nmos_switch, opamp_noninv, opamp_inv, rc_lowpass, divider_adc, mcu_i2c,
    xtal_osc,
)}
