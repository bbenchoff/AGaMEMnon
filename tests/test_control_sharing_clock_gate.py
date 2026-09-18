"""Control-sharing candidates ("mixed"/"dual") need the MCU-bus clock profile (2026-09-17).

Both profiles place a native consumer on local clock line 1, which bitgen accepts only under the
qualified MCU-bus GCLK0 profile (features/clocks.py). On a PLL-clocked design the candidate used to
route, reach bitgen, and abort the whole build although the isolated baseline had already succeeded;
which builds hit it depended on placement luck. The opportunity scan now offers no sharing profile
unless the baseline is bus-clocked.
"""
from agamemnon import cli


def _doc(bus_clocked, groups=2, ordinary=1):
    cells = {}
    for i in range(groups):
        cells["ff%d" % i] = {"type": "GENERIC_SLICE", "parameters": {"FF_USED": "1"},
                             "attributes": {"AGRV2K_CLOCK_ENABLE_NET": "en%d" % i}}
    for i in range(ordinary):
        cells["plain%d" % i] = {"type": "GENERIC_SLICE", "parameters": {"FF_USED": "1"}, "attributes": {}}
    if bus_clocked:
        cells["busclk"] = {"type": "MCU_BUS_CLOCK", "parameters": {}, "attributes": {}}
    return {"modules": {"top": {"cells": cells}}}


def test_sharing_profiles_offered_only_for_bus_clocked_designs():
    profiles, population = cli._control_sharing_opportunity(_doc(bus_clocked=True))
    assert profiles == ("mixed", "dual")
    assert population["bus_clocked"] is True and "skipped" not in population

    profiles, population = cli._control_sharing_opportunity(_doc(bus_clocked=False))
    assert profiles == ()
    assert population["bus_clocked"] is False
    assert population["skipped"] == "line1_requires_mcu_bus_clock"
    assert population["native_groups"] == 2 and population["ordinary_registers"] == 1


def test_no_opportunity_reports_no_skip():
    profiles, population = cli._control_sharing_opportunity(_doc(bus_clocked=False, groups=1, ordinary=0))
    assert profiles == () and "skipped" not in population
