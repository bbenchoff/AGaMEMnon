import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon.engine import bitgen, routing_admission, special_routes
from agamemnon.engine.claim_policy import ClaimPolicyError, evaluate_policy
from agamemnon.engine.claim_policy import PolicyDecision
from agamemnon.engine.features import routing as routing_feature
from agamemnon.engine.features.physical_io import PhysicalIoState
from agamemnon.engine.features.routing import FEATURE as ROUTING_FEATURE
from agamemnon.engine.registry import options_from


def _physical_io_state(**overrides):
    """A REAL PhysicalIoState, not a hand-listed SimpleNamespace.

    These stubs used to enumerate the six fields the resolver happened to touch,
    so adding a field to the production state made the resolver raise
    AttributeError here instead of exercising the path under test. Build the
    real dataclass and override only what the case needs, so the stub cannot
    drift from production again.
    """
    state = PhysicalIoState()
    for name, value in overrides.items():
        assert hasattr(state, name), "PhysicalIoState has no field %r" % name
        setattr(state, name, value)
    return state


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
OPTION = routing_admission.OPTION_NAME


def _row():
    row = {
        "feature_id": OPTION,
        "edge_id": "0" * 64,
        "row_identity": "0" * 64,
        "route": {
            "source": {
                "tile": "LogicTILE", "x": 5, "y": 4,
                "family": "RMUX", "index": 21,
            },
            "destination": {
                "tile": "LogicTILE", "x": 1, "y": 4,
                "family": "RMUX", "index": 31,
            },
        },
        "encoding": {
            "owner_tile": "LogicTILE", "owner_x": 2, "owner_y": 4,
            "cfg": "CFG_RMUX7",
            "set_selectors": [45, 46],
            "clear_selectors": [43],
            "owned_selectors": [43, 45, 46],
        },
        "registry_maturity": "experimental",
        "evidence_tier": "differentially_validated",
        "claim_domain": "exact differential routing-selector encoding",
        "strict_permission": "experimental-strict",
        "scope": {
            "device": "AGRV2KL48", "package": "L48",
            "coordinates": "exact-route-and-owner-coordinates",
            "composition": "exact-edge-only",
        },
        "evidence_refs": [{"path": "evidence.json", "sha256": "1" * 64}],
        "approval": {
            "state": "approved", "approved_by": "Brian Benchoff",
            "review_date": "2026-08-09",
            "source_admission": {"path": "source.json", "sha256": "b" * 64},
            "dossier": {"path": "dossier.json", "sha256": "c" * 64},
            "dossier_identity": "d" * 64,
            "admission_review": {"path": "approval.json", "sha256": "f" * 64},
        },
        "conflict_count": 0,
        "unknown_count": 0,
        "terminal_edge_overlap_count": 0,
        "retained_negative_refs": [{"path": "negative.json", "sha256": "2" * 64}],
    }
    row["edge_id"] = routing_admission.canonical_edge_id(row["route"])
    row["row_identity"] = routing_admission.canonical_identity(row)
    return row


def _manifest(rows):
    return {
        "accounting": {"admitted_rows": len(rows)},
        "non_claim": "Encoding-only experimental rows; no release or silicon claim.",
        "permission": {
            "allowed": "experimental-strict",
            "default_selection": "denied",
            "release_strict": "denied",
        },
        "policy_version": "D0-v1",
        "provenance": {
            "state": "reviewed-import" if rows else "bootstrap-empty",
            "source_admission_manifest_sha256": (
                rows[0]["approval"]["source_admission"]["sha256"] if rows else None
            ),
        },
        "rows": rows,
        "schema": routing_admission.SCHEMA,
        "scope": {"device": "AGRV2KL48", "package": "L48"},
    }


def _iotile_row():
    row = _row()
    row["route"]["source"].update(x=4, y=2, index=20)
    row["route"]["destination"].update(
        tile="IOTILE", x=0, y=2, index=30
    )
    row["encoding"].update(
        owner_tile="IOTILE", owner_x=0, owner_y=2,
        cfg="CFG_RMUX3", set_selectors=[45, 46], clear_selectors=[40, 41],
        owned_selectors=[40, 41, 45, 46],
    )
    row["edge_id"] = routing_admission.canonical_edge_id(row["route"])
    row["row_identity"] = routing_admission.canonical_identity(row)
    return row


def _chipdb(tmp_path, rows, include_topology=True):
    root = tmp_path / "chipdb"
    root.mkdir(parents=True)
    if rows:
        assert len(rows) == 1
        row = rows[0]

        def retain(name, value):
            path = root / name
            path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

        row["evidence_refs"] = [retain("evidence.json", {"evidence": "public"})]
        row["retained_negative_refs"] = [retain("negative.json", {"terminal_overlap": 0})]
        row["approval"]["source_admission"] = retain("source.json", {"rows": 1})
        dossier = {"campaign": "public-differential", "edge": row["edge_id"]}
        dossier["dossier_identity"] = \
            routing_admission.canonical_value_identity(dossier)
        row["approval"]["dossier"] = retain("dossier.json", dossier)
        row["approval"]["dossier_identity"] = dossier["dossier_identity"]
        review = {
            "schema": "agamemnon.routing-selector-admission-approval.v1",
            "decision": "approve-experimental-routing-selector",
            "edge_id": row["edge_id"],
            "route": row["route"],
            "encoding": row["encoding"],
            "evidence_tier": row["evidence_tier"],
            "registry_maturity": row["registry_maturity"],
            "strict_permission": row["strict_permission"],
            "approved_by": row["approval"]["approved_by"],
            "review_date": row["approval"]["review_date"],
            "source_admission": row["approval"]["source_admission"],
            "dossier": row["approval"]["dossier"],
            "dossier_identity": row["approval"]["dossier_identity"],
        }
        row["approval"]["admission_review"] = retain("approval.json", review)
        row["row_identity"] = routing_admission.canonical_identity(row)

    (root / routing_admission.FILENAME).write_text(
        json.dumps(_manifest(rows), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (root / "rrg_edges_full.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "src_tile", "src_x", "src_y", "src_res",
            "dst_tile", "dst_x", "dst_y", "dst_res", "cfg", "source", "tier",
        ))
        writer.writeheader()
        if include_topology:
            source = rows[0]["route"]["source"] if rows else _row()["route"]["source"]
            destination = (
                rows[0]["route"]["destination"]
                if rows else _row()["route"]["destination"]
            )
            encoding = rows[0]["encoding"] if rows else _row()["encoding"]
            writer.writerow({
                "src_tile": source["tile"], "src_x": source["x"],
                "src_y": source["y"],
                "src_res": "%s%02d" % (source["family"], source["index"]),
                "dst_tile": destination["tile"], "dst_x": destination["x"],
                "dst_y": destination["y"],
                "dst_res": "%s%02d" % (
                    destination["family"], destination["index"]
                ),
                "cfg": "%s[%s]" % (
                    encoding["cfg"],
                    ",".join(str(value) for value in encoding["set_selectors"]),
                ),
                "source": "observed", "tier": "fanin",
            })
    with (root / "wires.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("tile", "x", "y", "resource"))
        writer.writeheader()
        row = rows[0] if rows else _row()
        source = row["route"]["source"]
        destination = row["route"]["destination"]
        components = [source, destination]
        encoding = row["encoding"]
        if (encoding["owner_x"], encoding["owner_y"]) not in {
                (source["x"], source["y"]),
                (destination["x"], destination["y"]),
        }:
            components.append({
                "tile": encoding["owner_tile"], "x": encoding["owner_x"],
                "y": encoding["owner_y"], "family": "RMUX", "index": 0,
            })
        for component in components:
            writer.writerow({
                "tile": component["tile"], "x": component["x"],
                "y": component["y"],
                "resource": "%s%02d" % (
                    component["family"], component["index"]
                ),
            })
    with (root / "pips_full.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("x", "y", "mux", "sel", "byte", "mask"))
        writer.writeheader()
        encoding = (rows[0] if rows else _row())["encoding"]
        for offset, selector in enumerate(encoding["owned_selectors"]):
            writer.writerow({
                "x": encoding["owner_x"], "y": encoding["owner_y"],
                "mux": encoding["cfg"], "sel": selector,
                "byte": 100 + offset, "mask": 1 << offset,
            })
    return root


def _experimental(root):
    return options_from({
        "AGAMEMNON_DATA": str(root),
        "AGAMEMNON_DEVICE": "AGRV2KL48",
        "AGAMEMNON_STRICT_POLICY": "experimental-strict",
        "AGAMEMNON_EXPERIMENTAL_FEATURES": OPTION,
        OPTION: "1",
    })


def test_packaged_contract_authenticates_six_reviewed_rows_and_is_owned_by_routing():
    rows = routing_admission.load_manifest(CHIPDB)
    assert len(rows) == 6
    assert {row["edge_id"] for row in rows} == {
        "4ab0dfb71e0ecfb1f6b1d8236727ff8a22c5651a54eae3dbc8bdcf660a5a940f",
        "4f2db92041d8ec3041b5af51b22a250e5df5fe2ad46759358dfc33aa50c42f3d",
        "6adc4d96bdb243f5358cc0e0c8b64d4b3b8d52aea7380706251262f9cd271d54",
        "6b2122f6defd3bbfc9061208f4d418844965e11d71e7c45e845df3f52d3b5950",
        "8d278bf560625b75e4e586b17527c2d4552e2d43217d353c16a9b36547addaf2",
        "b129118a66972bb6b78cd8a54401d4478754856a5accb99391447b623fb25d64",
    }
    assert all(row["evidence_tier"] == "differentially_validated"
               and row["strict_permission"] == "experimental-strict"
               and row["scope"]["device"] == "AGRV2KL48"
               and row["scope"]["package"] == "L48"
               for row in rows)
    value = json.loads((CHIPDB / routing_admission.FILENAME).read_text(encoding="utf-8"))
    assert value["accounting"] == {"admitted_rows": 6}
    assert value["provenance"] == {
        "state": "reviewed-import",
        "source_admission_manifest_sha256":
            "84530caca717c9b519d7c4ae3d3e1c9696f135dc24d6223da809cca5521715d9",
    }
    assert routing_admission.FILENAME in ROUTING_FEATURE.descriptor.chipdb_files
    assert OPTION in ROUTING_FEATURE.descriptor.options


def test_campaign_identity_algorithms_have_fixed_known_answers():
    row = _row()
    assert row["edge_id"] == \
        "b95ea2584b3f8ccba26c7cdc394bc812fe4453f9d66c35db30c01ca94fb20073"
    dossier = {
        "campaign": "public-differential", "edge": row["edge_id"],
        "dossier_identity":
            "76e11fd10043de1c2864f83be86a06409e9acb6b255ccc99b75b37fae3496b36",
    }
    assert routing_admission.canonical_dossier_identity(dossier) == \
        dossier["dossier_identity"]


def test_exact_row_normalizes_once_for_architecture_and_bitgen(tmp_path):
    row = _row()
    root = _chipdb(tmp_path, [row])
    selected = routing_admission.selected_edge_map(_experimental(root), root)
    assert selected == {routing_admission.route_key(row): row}
    assert routing_admission.emission_entries(row) == (
        (2, 4, "CFG_RMUX7", 45), (2, 4, "CFG_RMUX7", 46),
    )
    assert routing_admission.clearing_entries(row) == ((2, 4, "CFG_RMUX7", 43),)

    tables = SimpleNamespace(
        chipdb_root=root,
        admission_binding={"test": True},
        admitted_edge=selected,
    )
    physical = _physical_io_state(
        padfeed_exact={(1, 4, 31, 5, 4, "RMUX", 21): []},
    )
    bram = SimpleNamespace(resolve_route=lambda *args, **kwargs: None)
    cell = {
        (2, 4, "CFG_RMUX7", 43): (100, 0x01),
        (2, 4, "CFG_RMUX7", 45): (101, 0x02),
        (2, 4, "CFG_RMUX7", 46): (102, 0x04),
    }
    state = ROUTING_FEATURE.prepare(
        pips=["X5Y4_RMUX21.X1Y4_RMUX31"], cell=cell,
        options=_experimental(root), tables=tables,
        physical_io_state=physical, exact_mcu_pips={}, mcu_cells={},
        mcu_exit_pairs={}, bram_feature=bram, bram_state=SimpleNamespace(),
        slice_config={}, left_vendor_slices=set(),
    )
    assert state.mapped == 1 and state.unmapped == 0 and state.predicted == 0
    assert state.clears == [(100, 0x01)]
    assert state.sets == [(101, 0x02), (102, 0x04)]
    assert state.admission_binding == {"test": True}


def test_activation_fails_closed_outside_exact_experimental_contract(tmp_path):
    row = _row()
    root = _chipdb(tmp_path, [row])
    assert routing_admission.selected_rows(options_from({}), root) == ()

    base = {
        "AGAMEMNON_DATA": str(root), "AGAMEMNON_DEVICE": "AGRV2KL48",
        "AGAMEMNON_EXPERIMENTAL_FEATURES": OPTION, OPTION: "1",
    }
    with pytest.raises(routing_admission.RoutingAdmissionError, match="experimental-strict"):
        routing_admission.selected_rows(options_from(base), root)
    with pytest.raises(routing_admission.RoutingAdmissionError, match="explicit feature ID"):
        routing_admission.selected_rows(options_from({
            **base, "AGAMEMNON_STRICT_POLICY": "experimental-strict",
            "AGAMEMNON_EXPERIMENTAL_FEATURES": "",
        }), root)
    with pytest.raises(routing_admission.RoutingAdmissionError, match="AGRV2KL48/L48"):
        routing_admission.selected_rows(options_from({
            **base, "AGAMEMNON_STRICT_POLICY": "experimental-strict",
            "AGAMEMNON_DEVICE": "AGRV2KL100",
        }), root)


def test_admitted_encoding_cannot_manufacture_topology(tmp_path):
    row = _row()
    root = _chipdb(tmp_path, [row], include_topology=False)
    with pytest.raises(routing_admission.RoutingAdmissionError, match="observed RRG topology"):
        routing_admission.selected_rows(_experimental(root), root)

    row = _row()
    root = _chipdb(tmp_path / "wire", [row])
    wires = root / "wires.csv"
    wires.write_text(
        wires.read_text(encoding="utf-8").replace("RMUX21", "RMUX99"),
        encoding="utf-8",
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="source wire"):
        routing_admission.selected_rows(_experimental(root), root)


def test_exact_iotile_row_supplies_absent_pip_only_in_experiment_and_emits_exact_bits(
        tmp_path):
    row = _iotile_row()
    root = _chipdb(tmp_path, [row], include_topology=False)

    assert routing_admission.selected_rows(options_from({}), root) == ()
    selected_rows = routing_admission.selected_rows(_experimental(root), root)
    assert selected_rows == (row,)
    selected = routing_admission.selected_edge_map(_experimental(root), root)

    class Capture:
        def __init__(self):
            self.pips = []

        def addPip(self, **kwargs):
            self.pips.append(kwargs)

    capture = Capture()
    wire_name = lambda x, y, resource: "X%sY%s_%s" % (x, y, resource)
    source_wire = "X4Y2_RMUX20"
    destination_wire = "X0Y2_RMUX30"
    seen = set()
    count = routing_feature._add_admitted_iotile_pips(
        ctx=capture, Loc=lambda x, y, z: (x, y, z), wire_name=wire_name,
        wireset={source_wire, destination_wire}, seen_pip=seen,
        rows=selected_rows, delay_for=lambda record: record["source"],
    )
    assert count == 1
    assert capture.pips == [{
        "name": "%s.%s" % (source_wire, destination_wire),
        "type": "EXPERIMENTAL_ROUTE",
        "srcWire": source_wire, "dstWire": destination_wire,
        "delay": "experimental-row-admission", "loc": (0, 2, 0),
    }]
    assert routing_feature._add_admitted_iotile_pips(
        ctx=capture, Loc=lambda x, y, z: (x, y, z), wire_name=wire_name,
        wireset={source_wire, destination_wire}, seen_pip=seen,
        rows=(), delay_for=lambda record: None,
    ) == 0

    tables = SimpleNamespace(
        chipdb_root=root, admission_binding={"test": True},
        admitted_edge=selected,
    )
    physical = _physical_io_state()
    cells = {
        (0, 2, "CFG_RMUX3", 40): (100, 0x01),
        (0, 2, "CFG_RMUX3", 41): (101, 0x02),
        (0, 2, "CFG_RMUX3", 45): (102, 0x04),
        (0, 2, "CFG_RMUX3", 46): (103, 0x08),
    }
    state = ROUTING_FEATURE.prepare(
        pips=["%s.%s" % (source_wire, destination_wire)],
        cell=cells, options=_experimental(root), tables=tables,
        physical_io_state=physical, exact_mcu_pips={}, mcu_cells={},
        mcu_exit_pairs={},
        bram_feature=SimpleNamespace(resolve_route=lambda *args, **kwargs: None),
        bram_state=SimpleNamespace(), slice_config={}, left_vendor_slices=set(),
    )
    assert state.mapped == 1 and state.unmapped == 0
    assert state.sets == [(102, 0x04), (103, 0x08)]
    assert state.clears == [(100, 0x01), (101, 0x02)]


@pytest.mark.parametrize("mutate, phrase", [
    (lambda row: row["route"]["destination"].update(tile="BramTILE"),
     "LogicTILE-to-IOTILE"),
    (lambda row: (
        row["route"]["destination"].update(y=3),
        row["encoding"].update(owner_y=3),
    ), "LogicTILE-to-IOTILE"),
    (lambda row: (
        row["route"]["destination"].update(x=1),
        row["encoding"].update(owner_x=1),
    ), "LogicTILE-to-IOTILE"),
    (lambda row: row["route"]["destination"].update(index=31),
     "LogicTILE-to-IOTILE"),
    (lambda row: row["encoding"].update(owner_tile="LogicTILE"),
     "LogicTILE-to-IOTILE"),
    (lambda row: row["encoding"].update(owner_x=1),
     "LogicTILE-to-IOTILE"),
    (lambda row: row["encoding"].update(cfg="CFG_RMUX5"), "owner group"),
    (lambda row: row["encoding"].update(
        set_selectors=[45, 50], owned_selectors=[40, 41, 45, 50]
    ), "selector field"),
    (lambda row: row["approval"].update(state="pending"), "approval"),
])
def test_iotile_supplement_rejects_wrong_tile_owner_group_field_and_authority(
        tmp_path, mutate, phrase):
    row = _iotile_row()
    mutate(row)
    row["edge_id"] = routing_admission.canonical_edge_id(row["route"])
    row["row_identity"] = routing_admission.canonical_identity(row)
    root = _chipdb(tmp_path, [row], include_topology=False)
    with pytest.raises(routing_admission.RoutingAdmissionError, match=phrase):
        routing_admission.selected_rows(_experimental(root), root)


def test_iotile_supplement_requires_every_physical_owner_cell(tmp_path):
    row = _iotile_row()
    root = _chipdb(tmp_path, [row], include_topology=False)
    pips = root / "pips_full.csv"
    retained = [
        line for line in pips.read_text(encoding="utf-8").splitlines()
        if not line.startswith("0,2,CFG_RMUX3,46,")
    ]
    pips.write_text("\n".join(retained) + "\n", encoding="utf-8")
    with pytest.raises(routing_admission.RoutingAdmissionError, match="owner cell"):
        routing_admission.selected_rows(_experimental(root), root)


@pytest.mark.parametrize("mutate", [
    lambda row: row["route"]["source"].update(index=22),
    lambda row: row["encoding"].update(
        set_selectors=[44, 46], owned_selectors=[43, 44, 46]
    ),
])
def test_approval_artifact_binds_exact_route_and_encoding(tmp_path, mutate):
    row = _row()
    root = _chipdb(tmp_path, [row])
    mutate(row)
    row["edge_id"] = routing_admission.canonical_edge_id(row["route"])
    row["row_identity"] = routing_admission.canonical_identity(row)
    (root / routing_admission.FILENAME).write_text(
        json.dumps(_manifest([row]), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="exact row authority"):
        routing_admission.selected_rows(_experimental(root), root)


def test_dossier_identity_is_recomputed_from_authenticated_json(tmp_path):
    row = _row()
    root = _chipdb(tmp_path, [row])
    dossier_path = root / row["approval"]["dossier"]["path"]
    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    dossier["substituted"] = True
    dossier_path.write_text(json.dumps(dossier, sort_keys=True) + "\n", encoding="utf-8")
    row["approval"]["dossier"]["sha256"] = hashlib.sha256(
        dossier_path.read_bytes()
    ).hexdigest()
    row["row_identity"] = routing_admission.canonical_identity(row)
    (root / routing_admission.FILENAME).write_text(
        json.dumps(_manifest([row]), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="dossier identity"):
        routing_admission.selected_rows(_experimental(root), root)


@pytest.mark.parametrize("option", [
    "AGAMEMNON_TRUE_TOPO", "AGAMEMNON_NO_INTRA_RMUX",
    "AGAMEMNON_OBS_IMUX", "AGAMEMNON_NO_EXIT_WL",
    "AGAMEMNON_BRAM_APPROACH", "AGAMEMNON_BRAM_PORTB_MCU_EXIT",
    "AGAMEMNON_BRAM_PORTB_EXIT",
])
def test_admission_rejects_graph_modifiers(tmp_path, option):
    row = _row()
    root = _chipdb(tmp_path, [row])
    values = dict(_experimental(root).environ)
    values[option] = "1"
    with pytest.raises(routing_admission.RoutingAdmissionError, match="graph modifier"):
        routing_admission.selected_rows(options_from(values), root)


def test_admission_rejects_static_dead_and_exit_pruned_edges(tmp_path):
    row = _row()
    root = _chipdb(tmp_path / "dead", [row])
    (root / "dead_edges_silicon.csv").write_text(
        'edge\n"RMUX21@5,4->RMUX31@1,4"\n', encoding="utf-8"
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="silicon-dead"):
        routing_admission.selected_rows(_experimental(root), root)

    row = _row()
    root = _chipdb(tmp_path / "exit", [row])
    (root / "exit_feeder_whitelist.csv").write_text(
        "dst_res,dst_x,dst_y,src_res,src_x,src_y,gpio_bit,kind\n"
        "RMUX31,1,4,RMUX22,5,4,0,test\n",
        encoding="utf-8",
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="exit-feeder"):
        routing_admission.selected_rows(_experimental(root), root)


def test_loader_authenticates_public_references_and_tile_owner_cells(tmp_path):
    row = _row()
    root = _chipdb(tmp_path, [row])
    assert routing_admission.selected_rows(_experimental(root), root) == (row,)

    evidence = root / row["evidence_refs"][0]["path"]
    evidence.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(routing_admission.RoutingAdmissionError, match="hash mismatch"):
        routing_admission.selected_rows(_experimental(root), root)

    row = _row()
    row["route"]["source"]["tile"] = "IOTILE"
    row["edge_id"] = routing_admission.canonical_edge_id(row["route"])
    row["row_identity"] = routing_admission.canonical_identity(row)
    root = _chipdb(tmp_path / "tile", [row])
    topology = root / "rrg_edges_full.csv"
    topology.write_text(
        topology.read_text(encoding="utf-8").replace(
            "LogicTILE,5,4,RMUX21", "IOTILE,5,4,RMUX21"
        ),
        encoding="utf-8",
    )
    with pytest.raises(routing_admission.RoutingAdmissionError, match="LogicTILE"):
        routing_admission.selected_rows(_experimental(root), root)


def test_runtime_rejects_two_admitted_rows_in_one_owner_field(tmp_path):
    first = _row()
    second = _row()
    second["edge_id"] = "9" * 64
    second["route"]["source"]["index"] = 22
    second["edge_id"] = routing_admission.canonical_edge_id(second["route"])
    second["encoding"]["set_selectors"] = [43, 46]
    second["encoding"]["clear_selectors"] = [45]
    second["row_identity"] = routing_admission.canonical_identity(second)
    first["row_identity"] = routing_admission.canonical_identity(first)
    admitted = {
        routing_admission.route_key(first): first,
        routing_admission.route_key(second): second,
    }
    tables = SimpleNamespace(
        chipdb_root=tmp_path, admission_binding={}, admitted_edge=admitted,
    )
    physical = _physical_io_state()
    bram = SimpleNamespace(resolve_route=lambda *args, **kwargs: None)
    cell = {
        (2, 4, "CFG_RMUX7", 43): (100, 0x01),
        (2, 4, "CFG_RMUX7", 45): (101, 0x02),
        (2, 4, "CFG_RMUX7", 46): (102, 0x04),
    }
    with pytest.raises(SystemExit, match="composition uses multiple rows"):
        ROUTING_FEATURE.prepare(
            pips=[
                "X5Y4_RMUX21.X1Y4_RMUX31",
                "X5Y4_RMUX22.X1Y4_RMUX31",
            ],
            cell=cell, options=options_from({}), tables=tables,
            physical_io_state=physical, exact_mcu_pips={}, mcu_cells={},
            mcu_exit_pairs={}, bram_feature=bram, bram_state=SimpleNamespace(),
            slice_config={}, left_vendor_slices=set(),
        )


def test_runtime_rejects_generic_route_in_admitted_owner_field(tmp_path):
    admitted = _row()
    admitted_map = {routing_admission.route_key(admitted): admitted}
    generic_key = (2, 4, "RMUX", 46, "RMUX", 5, 4, 22)
    tables = SimpleNamespace(
        chipdb_root=tmp_path, admission_binding={}, admitted_edge=admitted_map,
        archival_legacy=False, clean_edge={generic_key: (3, 5)},
        relative_edge={}, group_context={},
    )
    physical = _physical_io_state()
    bram = SimpleNamespace(resolve_route=lambda *args, **kwargs: None)
    cell = {
        (2, 4, "CFG_RMUX7", 43): (100, 0x01),
        (2, 4, "CFG_RMUX7", 45): (101, 0x02),
        (2, 4, "CFG_RMUX7", 46): (102, 0x04),
    }
    with pytest.raises(SystemExit, match="reuses admitted owner field"):
        ROUTING_FEATURE.prepare(
            pips=[
                "X5Y4_RMUX21.X1Y4_RMUX31",
                "X5Y4_RMUX22.X2Y4_RMUX46",
            ],
            cell=cell, options=options_from({}), tables=tables,
            physical_io_state=physical, exact_mcu_pips={}, mcu_cells={},
            mcu_exit_pairs={}, bram_feature=bram, bram_state=SimpleNamespace(),
            slice_config={}, left_vendor_slices=set(),
        )


def test_routing_cell_map_honors_custom_chipdb_root(tmp_path):
    root = tmp_path / "chipdb"
    root.mkdir()
    (root / "pips_full.csv").write_text(
        "x,y,mux,sel,byte,mask\n2,4,CFG_RMUX7,45,999,8\n",
        encoding="utf-8",
    )
    cell, groups = ROUTING_FEATURE.load_cell_map(root)
    assert cell == {(2, 4, "CFG_RMUX7", 45): (999, 8)}
    assert groups[(2, 4, "CFG_RMUX7")] == {45: (999, 8)}


def test_bitgen_uses_one_chipdb_root_and_rejects_policy_emitter_split(
        tmp_path, monkeypatch):
    custom = tmp_path / "custom-chipdb"
    custom.mkdir()
    (custom / special_routes.CATALOG_NAME).write_bytes(
        (CHIPDB / special_routes.CATALOG_NAME).read_bytes()
    )
    routed = tmp_path / "routed.json"
    routed.write_text(json.dumps({"modules": {"top": {
        "attributes": {"top": 1}, "cells": {}, "netnames": {},
    }}}), encoding="utf-8")
    policy_binding = {
        "routing_selector_admission_sha256": "1" * 64,
        "routing_selector_row_identities": ["2" * 64],
    }
    decision = PolicyDecision(
        "experimental-strict",
        ({"kind": "routing_selector_manifest", "name": OPTION, **policy_binding},),
        (OPTION,),
    )
    captured = {}

    monkeypatch.setattr(bitgen, "evaluate_policy", lambda options: decision)

    def prepare(_routed, _options, chipdb_root, document=None):
        assert document is not None
        captured["root"] = chipdb_root
        return SimpleNamespace(routing=SimpleNamespace(admission_binding=None))

    monkeypatch.setattr(bitgen, "prepare_design", prepare)
    with pytest.raises(SystemExit, match="policy/emitter admission binding mismatch"):
        bitgen.build(routed, tmp_path / "unused.bin", environ={
            "AGAMEMNON_DATA": str(custom),
        })
    assert captured["root"] == custom


@pytest.mark.parametrize("mutate, phrase", [
    (lambda row: row.update(registry_maturity="release"), "maturity"),
    (lambda row: row.update(evidence_tier="decoded"), "evidence"),
    (lambda row: row["scope"].update(package="L100"), "scope"),
    (lambda row: row["approval"].update(state="pending"), "approval"),
    (lambda row: row["approval"].update(approved_by="Mallory"), "approval"),
    (lambda row: row["approval"].update(review_date="2099-01-01"), "future"),
    (lambda row: row.update(conflict_count=1), "conflict"),
    (lambda row: row["encoding"].update(cfg="CFG_RMUX5"), "identity"),
])
def test_row_contract_rejects_tier_scope_approval_conflict_and_tamper(mutate, phrase):
    row = _row()
    mutate(row)
    if phrase != "identity":
        row["row_identity"] = routing_admission.canonical_identity(row)
    with pytest.raises(routing_admission.RoutingAdmissionError, match=phrase):
        routing_admission.validate_manifest(_manifest([row]))


def test_claim_policy_lists_exact_selected_row(tmp_path):
    row = _row()
    root = _chipdb(tmp_path, [row])
    decision = evaluate_policy(_experimental(root))
    selected = [item for item in decision.selected if item["kind"] == "routing_selector"]
    assert len(selected) == 1
    assert selected[0]["edge_id"] == row["edge_id"]
    assert selected[0]["row_identity"] == row["row_identity"]

    release = options_from({OPTION: "1"})
    with pytest.raises(ClaimPolicyError, match="experimental-strict"):
        evaluate_policy(release)


def test_unused_experiment_is_byte_noop_and_hash_binds_policy_sidecar(tmp_path):
    routed = (
        ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
        "logic" / "id_scratch8_L48_routed.json"
    )
    release_output = tmp_path / "release.bin"
    experimental_output = tmp_path / "experimental.bin"
    sidecar = tmp_path / "experimental.policy.json"
    release_environment = {
        "AGAMEMNON_DEVICE": "AGRV2KL48",
        "AGAMEMNON_HSE": "8",
        "AGAMEMNON_SYSCLK": "10",
    }
    bitgen.build(str(routed), str(release_output), environ=release_environment)
    bitgen.build(str(routed), str(experimental_output), environ={
        **release_environment,
        "AGAMEMNON_DEVICE": "AGRV2KL48",
        "AGAMEMNON_STRICT_POLICY": "experimental-strict",
        "AGAMEMNON_EXPERIMENTAL_FEATURES": OPTION,
        "AGAMEMNON_POLICY_SIDECAR": str(sidecar),
        OPTION: "1",
    })
    assert experimental_output.read_bytes() == release_output.read_bytes()
    policy = json.loads(sidecar.read_text(encoding="utf-8"))
    assert policy["bindings"]["routing_selector_admission_sha256"] == \
        routing_admission.manifest_identity(CHIPDB)
    assert policy["bindings"]["routing_selector_row_identities"] == [
        row["row_identity"] for row in routing_admission.load_manifest(CHIPDB)
    ]
