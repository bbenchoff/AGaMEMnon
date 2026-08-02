import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_local_interrupt_lanes_have_differential_silicon_evidence():
    evidence = [json.loads(line) for line in
                (ROOT / "qualification" / "mcu_local_int_evidence.jsonl").read_text(
                    encoding="utf-8").splitlines() if line]
    individual = [row for row in evidence if row["lane"] != "all"]
    assert [(row["lane"], row["fabric_level"]) for row in individual] == [
        (bit, level) for bit in range(4) for level in (1, 0)]
    assert all(row["build"] == row["hardware"] == "pass" for row in evidence)
    assert all(row["fcb_status"] == "0x000f0002" for row in evidence)
    for bit in range(4):
        high, low = individual[2 * bit:2 * bit + 2]
        assert high["mailbox"][1:4] == [0x4C494E54, 0x80000010 + bit, 1]
        assert high["mailbox"][5] & (1 << (16 + bit))
        assert low["mailbox"][1:4] == [0, 0, 0]
        assert not (low["mailbox"][10] & (1 << (16 + bit)))
        assert high["firmware_sha256"] == low["firmware_sha256"]
    all_low = evidence[-1]
    assert all_low["lane"] == "all"
    assert all_low["mailbox"][10] & 0x000F0000 == 0


def test_local_interrupt_firmware_masks_all_lanes_before_enabling_selected_lane():
    source = (ROOT / "examples" / "riscv_mcu" / "local_interrupt0.c").read_text(
        encoding="utf-8")
    clear = source.index("ag32_disable_machine_interrupt_mask(0x000f0000u)")
    configure = source.index("ag32_fcb_config")
    enable = source.index(
        "ag32_enable_machine_interrupt_mask(AG32_MIE_LOCAL(LOCAL_INT_BIT))")
    assert clear < configure < enable
    assert "cause == 16u + LOCAL_INT_BIT" in source
    for bit in range(1, 4):
        wrapper = (ROOT / "examples" / "riscv_mcu" /
                   f"local_interrupt{bit}.c").read_text(encoding="utf-8")
        assert f"#define LOCAL_INT_BIT {bit}u" in wrapper
