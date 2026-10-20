rollouts 132; contaminated 0; oracle != 1: 0

## Overall
| group | haiku | sonnet | opus |
|---|---|---|---|
| all | 100% (44/44) | 57% (25/44) | 95% (42/44) |

## By family
| group | haiku | sonnet | opus |
|---|---|---|---|
| ldo_reg | 100% (5/5) | 20% (1/5) | 100% (5/5) |
| led_driver | 100% (5/5) | 60% (3/5) | 100% (5/5) |
| mcu_i2c | 100% (5/5) | 40% (2/5) | 100% (5/5) |
| nmos_switch | 100% (5/5) | 80% (4/5) | 100% (5/5) |
| npn_switch | 100% (5/5) | 80% (4/5) | 100% (5/5) |
| sys_analog_frontend | 100% (5/5) | 80% (4/5) | 100% (5/5) |
| sys_clocked_mcu | 100% (5/5) | 80% (4/5) | 100% (5/5) |
| sys_motor_ctrl | 100% (5/5) | 40% (2/5) | 60% (3/5) |
| sys_sensor_node | 100% (4/4) | 25% (1/4) | 100% (4/4) |

## By number of faults
| group | haiku | sonnet | opus |
|---|---|---|---|
| 3 | 100% (13/13) | 77% (10/13) | 100% (13/13) |
| 4 | 100% (13/13) | 31% (4/13) | 85% (11/13) |
| 5 | 100% (9/9) | 56% (5/9) | 100% (9/9) |
| 6 | 100% (9/9) | 67% (6/9) | 100% (9/9) |

## By tool mode
| group | haiku | sonnet | opus |
|---|---|---|---|
| full | 100% (28/28) | 54% (15/28) | 93% (26/28) |
| no_autoroute | 100% (16/16) | 62% (10/16) | 100% (16/16) |

## Failing gate/check counts among failed rollouts
- rules: 14
- topology: 9
- layout: 8
