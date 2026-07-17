import pytest

from tools.bundle.openocd_audit import classify_dap_probe, validate_corresponding_source


def test_dap_parser_probe_classifies_compatible_and_stock_output():
    assert classify_dap_probe("Error: DAP name invalid!") is True
    assert classify_dap_probe("Error: unknown option -dap") is False
    assert classify_dap_probe("unrelated startup failure") is None


def test_corresponding_source_requires_license_and_riscv_dap_source(tmp_path):
    with pytest.raises(RuntimeError, match="GPL license"):
        validate_corresponding_source(tmp_path)
    (tmp_path / "COPYING").write_text("GPL-2.0", encoding="utf-8")
    with pytest.raises(RuntimeError, match="riscv.c"):
        validate_corresponding_source(tmp_path)
    source = tmp_path / "src" / "target" / "riscv" / "riscv.c"
    source.parent.mkdir(parents=True)
    source.write_text("/* RISC-V target with ADIv5 DAP support. */", encoding="utf-8")
    assert validate_corresponding_source(tmp_path) == tmp_path.resolve()
