import pytest

from agamemnon.engine.bitgen import prepare_design
from agamemnon.engine.features.routing import FEATURE as ROUTING_FEATURE
from agamemnon.engine.registry import options_from


def _net(bit, route):
    return {"bits": [bit], "attributes": {"ROUTING": route}}


def test_rejects_two_exact_routes_that_own_the_same_physical_muxes():
    # Reproduction of the BRAM workbench failure: AddressB localized zeros
    # still owned RMUX60/RMUX84 when a hand-patched control net added exact
    # ByteEnA1/ClkEn0 branches through the same muxes.  Every pip encoded and
    # bitgen reported zero debt, but the selector-codeword union was invalid.
    module = {"netnames": {
        "addr_b9_zero": _net(
            9,
            "X14Y4_OMUX32;;1;X14Y4_RMUX60;"
            "X14Y4_OMUX32.X14Y4_RMUX60;5",
        ),
        "addr_b11_zero": _net(
            11,
            "X14Y4_OMUX44;;1;X14Y4_RMUX84;"
            "X14Y4_OMUX44.X14Y4_RMUX84;5",
        ),
        "write_controls": _net(
            20,
            "X15Y4_OMUX02;;1;X14Y4_RMUX60;"
            "X17Y8_RMUX03.X14Y4_RMUX60;5;X14Y4_RMUX84;"
            "X14Y7_RMUX44.X14Y4_RMUX84;5",
        ),
    }}

    with pytest.raises(ValueError, match="cross-net physical mux ownership conflict") as caught:
        ROUTING_FEATURE.validate_mux_ownership(module)
    message = str(caught.value)
    assert "X14Y4_RMUX60=addr_b9_zero,write_controls" in message
    assert "X14Y4_RMUX84=addr_b11_zero,write_controls" in message


def test_allows_fanout_and_aliases_of_one_logical_net():
    route = (
        "X14Y4_OMUX17;;1;X14Y4_RMUX30;X14Y4_OMUX17.X14Y4_RMUX30;5;"
        "X14Y4_RMUX30;X14Y4_OMUX17.X14Y4_RMUX30;5"
    )
    module = {"netnames": {
        "ren": _net(20, route),
        "ren_alias": _net(20, route),
    }}
    assert ROUTING_FEATURE.validate_mux_ownership(module) == 2


def test_constant_presentations_are_not_treated_as_signal_aliases():
    module = {"netnames": {
        "zero_a": _net("0", "X1Y1_OMUX00;;1;X1Y1_RMUX01;a;5"),
        "zero_b": _net("0", "X1Y1_OMUX02;;1;X1Y1_RMUX01;b;5"),
    }}
    with pytest.raises(ValueError, match="X1Y1_RMUX01=zero_a,zero_b"):
        ROUTING_FEATURE.validate_mux_ownership(module)


def test_prepare_design_fails_closed_on_cross_net_mux_ownership(tmp_path):
    routed = tmp_path / "conflicting-routed.json"
    routed.write_text("""{
      "modules": {"top": {
        "netnames": {
          "addr_b9_zero": {
            "bits": [9],
            "attributes": {"ROUTING": "X14Y4_OMUX32;;1;X14Y4_RMUX60;X14Y4_OMUX32.X14Y4_RMUX60;5"}
          },
          "addr_b11_zero": {
            "bits": [11],
            "attributes": {"ROUTING": "X14Y4_OMUX44;;1;X14Y4_RMUX84;X14Y4_OMUX44.X14Y4_RMUX84;5"}
          },
          "write_controls": {
            "bits": [20],
            "attributes": {"ROUTING": "X15Y4_OMUX02;;1;X14Y4_RMUX60;X17Y8_RMUX03.X14Y4_RMUX60;5;X14Y4_RMUX84;X14Y7_RMUX44.X14Y4_RMUX84;5"}
          }
        },
        "cells": {}, "ports": {}
      }}
    }""", encoding="utf-8")

    with pytest.raises(SystemExit, match="cross-net physical mux ownership conflict") as caught:
        prepare_design(routed, options_from({}))
    message = str(caught.value)
    assert "X14Y4_RMUX60=addr_b9_zero,write_controls" in message
    assert "X14Y4_RMUX84=addr_b11_zero,write_controls" in message
