"""Session-owned device databases for tests that inspect the generated graph.

These fixtures are built from the current checkout, never a developer's ignored
in-tree cache. Explicit native-test database overrides remain caller-owned.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STRICT_ENV = (
    "AGAMEMNON_CONDUCTION_GATE=1", "AGAMEMNON_HW_CARRY=1",
    "AGAMEMNON_LEDPADS=1", "AGAMEMNON_STRICT_GATE=1",
    "AGAMEMNON_XBAR_CONDUCT=1", "AGAMEMNON_CLEAN_SEL_GATE=1",
)
PROFILES = {
    "strict": (),
    "tiered": ("AGAMEMNON_ROUTING_ADMISSION=tiered",),
    "strict_pcf": (
        "AGAMEMNON_PHYSICAL_IO=1", "AGAMEMNON_PADFEED_TOP=1",
        "AGAMEMNON_HARDEN_PADFEED=1", "AGAMEMNON_LEFT_PAD_OUT=1",
    ),
}
RUNTIME_ASSETS = (
    "clock_reach_silicon_negative.csv", "master_conduction.csv",
    "mcu_ahb32_corridors.csv", "mcu_ahb32_pip_cfg.csv",
    "mcu_ahb32_addr_corridors.csv", "mcu_logic_consumer_footprints.csv",
    "mcu_endpoint_capabilities.csv", "mcu_endpoint_capability_manifest.json",
    "mcu_hwdata_lanes.csv", "mcu_slave_ahb_request_control_independent_paths.csv",
    "mcu_slave_ahb_request_payload_paths.csv", "mcu_slave_ahb_haddr2_dynamic_paths.csv",
    "mcu_slave_ahb_haddr29_sram_base_paths.csv", "mcu_region_witness.csv",
    "soft_ripple_region_witness.csv", "pad_oe_L48_left_corridors.csv",
    "pad_input_L48_left_corridors.csv", "bram_tmux9_source_paths.csv",
)


class DatabaseFixtures:
    def __init__(self):
        self.workspace = None
        self.requested = {}
        self.ready = set()

    def path(self, profile, override=None):
        if profile not in PROFILES:
            raise ValueError("Unknown test database profile: " + profile)
        if override is not None and override in os.environ:
            return Path(os.environ[override])
        if self.workspace is None:
            self.workspace = tempfile.TemporaryDirectory(prefix="agamemnon-test-devdb-")
        path = Path(self.workspace.name) / profile
        self.requested[profile] = path
        return path

    def prepare(self):
        # Each subprocess exits before the next graph is generated, bounding
        # memory use and avoiding shared-cache races between pytest sessions.
        for profile, output in sorted(self.requested.items()):
            if profile in self.ready:
                continue
            command = [sys.executable, str(ROOT / "agamemnon/engine/emit_uarch_db.py"),
                       "--arch", str(ROOT / "agamemnon/engine/arch.py"),
                       "--data", str(ROOT / "agamemnon/chipdb"), "--out", str(output)]
            for setting in STRICT_ENV + PROFILES[profile]:
                command.extend(("--env", setting))
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("AGAMEMNON_", "AGRV2K_"))}
            run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                 text=True, timeout=1800)
            if run.returncode:
                raise RuntimeError("Test database generation failed for %s:\n%s\n%s" %
                                   (profile, run.stdout, run.stderr))
            for name in ("dev_pips.csv", "dev_belpins.csv", "dev_meta.csv"):
                if not (output / name).is_file():
                    raise RuntimeError("Generated test database is missing " + name)
            for name in RUNTIME_ASSETS:
                source = ROOT / "agamemnon/chipdb" / name
                if source.is_file():
                    shutil.copyfile(source, output / name)
            self.ready.add(profile)

    def close(self):
        if self.workspace is not None:
            self.workspace.cleanup()
        self.workspace = None
        self.requested.clear()
        self.ready.clear()


DATABASES = DatabaseFixtures()
devdb_path = DATABASES.path
