"""DT8 colour temperature (TriggerType 47): Kelvin <-> the stored mirek / 4 byte."""
import pytest

from edidio_spektra_ai import commands
from edidio_spektra_ai.spektra_validate import _check_trigger_fits


def test_build_encodes_mirek_over_4():
    cmd = commands.build({"do": "dt8_colour_temp", "line": 1, "address": 5, "kelvin": 4000})
    assert cmd["commandtype"] == 47
    assert cmd["linemask"] == 1 and cmd["target"] == 5
    assert cmd["value"] == 62            # 250 mirek / 4 = 62.5 -> 62 (248 mirek)


@pytest.mark.parametrize("kelvin,value", [(2700, 93), (3000, 83), (6500, 38), (1000, 250)])
def test_kelvin_to_value(kelvin, value):
    assert commands.kelvin_to_value(kelvin) == value
    # what the controller sends is within one 4-mirek step of what was asked
    assert abs(1_000_000 / kelvin - value * 4) <= 2


def test_value_fits_one_byte_at_the_extremes():
    assert commands.kelvin_to_value(20000) == 12
    assert commands.kelvin_to_value(980) == 255


def test_out_of_range_kelvin_is_refused():
    with pytest.raises(commands.CommandError):
        commands.build({"do": "dt8_colour_temp", "line": 1, "broadcast": True, "kelvin": 500})


def test_describe_shows_kelvin():
    cmd = commands.build({"do": "dt8_colour_temp", "line": 2, "group": 3, "kelvin": 2700})
    assert commands.describe(cmd) == "DT8 colour temperature 2688 K (value 93) -> group 3 line 2"
    assert "dt8_colour_temp" in commands.ACTIONS
    raw = {"commandtype": 47, "linemask": 1, "target": 5, "value": 4000}
    assert commands.describe(raw).startswith("DT8 colour temperature invalid (value 4000)")


def test_validation_explains_a_kelvin_value():
    out = []
    item = {"action": {"commandtype": 47, "zone": 0, "linemask": 1, "target": 80,
                       "value": 4000, "query": 0}}
    _check_trigger_fits(item, "mac", "inputs", 0, out)
    assert len(out) == 1
    assert "looks like Kelvin" in out[0].message and "use 62" in out[0].message
