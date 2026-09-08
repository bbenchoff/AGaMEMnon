"""Execution budgets stop hung tools without accepting incomplete output."""
import argparse
import subprocess
import sys
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


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf')])
def test_invalid_attempt_limit_is_rejected_before_build_work(timeout):
    with pytest.raises(SystemExit) as exc:
        cli.cmd_build(argparse.Namespace(attempt_timeout=timeout))
    assert exc.value.code == 2


def test_routing_marker_with_timeout_exit_cannot_be_accepted():
    # A timeout may preserve partial nextpnr output, including this marker.
    # The synthetic timeout status must still keep the attempt incomplete.
    assert not cli._route_and_timing_succeeded('Routing complete', 124)
