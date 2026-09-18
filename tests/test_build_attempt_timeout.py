"""Execution budgets stop hung tools without accepting incomplete output."""
import argparse
import os
import subprocess
import sys
import time
import pytest
from agamemnon import cli


def test_child_timeout_stops_a_running_tool():
    with pytest.raises(subprocess.TimeoutExpired):
        cli._run_child([sys.executable, '-c', 'import time; time.sleep(30)'],
                       capture_output=True, text=True, timeout=0.1)


def test_completed_child_keeps_its_output_and_exit_status():
    result = cli._run_child([sys.executable, '-c', 'print("complete")'],
                           capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == 'complete'


@pytest.mark.skipif(os.name == "nt", reason="POSIX timed subprocess contract")
def test_timed_child_preserves_input_and_checked_errors():
    with pytest.raises(subprocess.CalledProcessError) as exc:
        cli._run_child(
            [sys.executable, "-c", "import sys; print(sys.stdin.read()); sys.exit(7)"],
            input="payload", capture_output=True, text=True, timeout=10, check=True,
        )
    assert exc.value.returncode == 7
    assert exc.value.stdout.strip() == "payload"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup")
def test_timeout_terminates_descendants_holding_the_output_pipe(tmp_path):
    marker = tmp_path / "descendant-survived"
    descendant = (
        "import pathlib, time; time.sleep(2); "
        "pathlib.Path(%r).write_text('alive')" % str(marker)
    )
    parent = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', %r]); "
        "print('started', flush=True); time.sleep(30)" % descendant
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        cli._run_child([sys.executable, "-c", parent],
                       capture_output=True, text=True, timeout=0.3)
    assert time.monotonic() - started < 1.5
    assert b"started" in exc.value.stdout
    # A killed parent alone leaves the grandchild running with the capture pipe
    # open. The timeout must stop the entire tree before that child can write.
    time.sleep(2.1)
    assert not marker.exists()


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf')])
def test_invalid_attempt_limit_is_rejected_before_build_work(timeout):
    with pytest.raises(SystemExit) as exc:
        cli.cmd_build(argparse.Namespace(attempt_timeout=timeout))
    assert exc.value.code == 2


def test_routing_marker_with_timeout_exit_cannot_be_accepted():
    # A timeout may preserve partial nextpnr output, including this marker.
    # The synthetic timeout status must still keep the attempt incomplete.
    assert not cli._route_and_timing_succeeded('Routing complete', 124)
