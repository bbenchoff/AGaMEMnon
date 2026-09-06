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


def test_exact_sanitizer_guard_does_not_exempt_other_lines_or_files(tmp_path, monkeypatch):
    source = sorted(check_path_leaks.SAFE_GUARD_FILES)[0]
    guard = next(line for line in source.read_bytes().splitlines()
                 if line.strip().startswith(b"forbidden ="))
    admitted = tmp_path / "canonicalize_routed.py"
    unrelated = tmp_path / "other.py"
    monkeypatch.setattr(check_path_leaks, "SAFE_GUARD_FILES", frozenset({admitted.resolve()}))
    admitted.write_bytes(guard + b"\n")
    unrelated.write_bytes(guard + b"\n")
    assert check_path_leaks.find_leaks([admitted]) == []
    assert len(check_path_leaks.find_leaks([unrelated])) == 1
    admitted.write_bytes(guard + b" # " + b"C:" + b"/Us" + b"ers/alice/private\n")
    assert len(check_path_leaks.find_leaks([admitted])) == 1
