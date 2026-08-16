from pathlib import Path

from tools import recover_wedged_ag32 as recovery


def test_recovery_uses_debug_module_ndmreset_without_memory_or_flash_commands():
    commands = recovery.recovery_commands("agrv2k.dap")
    blob = "\n".join(commands)
    assert "0x00000003" in blob
    assert "0x00000001" in blob
    assert commands.count("agrv2k.dap apreg 0 0x04 0x40") == 2
    assert not any(token in blob for token in ("mww", "flash", "erase", "program"))


def test_verification_halts_reads_device_id_then_resets():
    assert recovery.verification_commands() == [
        "init", "halt", "mdw 0x03000100", "reset", "shutdown"
    ]


def test_openocd_prefix_keeps_paths_as_single_arguments():
    executable = Path("C:/Open OCD/openocd.exe")
    scripts = Path("C:/Open OCD/scripts")
    config = Path("target cfg/agrv2k.cfg")
    prefix = recovery.command_prefix(executable, scripts, config)
    assert prefix == [
        str(executable), "-s", str(scripts),
        "-c", "set ADAPTER cmsis-dap", "-f", str(config),
    ]


def test_device_id_parser_is_exact_and_case_insensitive():
    assert recovery.device_id("0x03000100: 40200001 ") == 0x40200001
    assert recovery.device_id("0x03000100: DEADBEEF\n") == 0xDEADBEEF
    assert recovery.device_id("no readback") is None
