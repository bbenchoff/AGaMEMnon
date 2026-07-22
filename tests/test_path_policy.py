from pathlib import Path

from tools import check_path_leaks


def test_path_policy_detects_windows_and_posix_homes(tmp_path):
    clean = tmp_path / "clean.txt"
    clean.write_text("agamemnon/chipdb/data.json\n/usr/bin/python\n<WORKBENCH>/capture.bin\n")
    win = tmp_path / "win.json"
    win.write_text('{"src":"C:' + r'\\Us' + r'ers\\alice\\repo\\top.v"}')
    posix = tmp_path / "posix.txt"
    posix.write_text("/ho" + "me/alice/repo/top.v\n")
    leaks = check_path_leaks.find_leaks([clean, win, posix])
    assert [(path.name, line) for path, line, _ in leaks] == [("win.json", 1), ("posix.txt", 1)]
