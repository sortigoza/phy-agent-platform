import subprocess
import sys

from phy.config import resolve_paths
from phy.locks import arxiv_lock, phy_lock

TRY_STAGE = """
from phy.config import resolve_paths
from phy.locks import phy_lock
with phy_lock(resolve_paths()):
    print("stage ran")
"""


def run_stage_in_other_process():
    return subprocess.run([sys.executable, "-c", TRY_STAGE], capture_output=True, text=True)


def test_held_phy_lock_makes_other_process_exit_zero_without_running(phy_home):
    phy_home.mkdir()
    with phy_lock(resolve_paths()):
        result = run_stage_in_other_process()
    assert result.returncode == 0
    assert "stage ran" not in result.stdout
    assert "lock.held" in result.stdout + result.stderr


def test_free_phy_lock_lets_the_stage_run(phy_home):
    phy_home.mkdir()
    with phy_lock(resolve_paths()):
        pass
    result = run_stage_in_other_process()
    assert result.returncode == 0
    assert "stage ran" in result.stdout


def test_arxiv_lock_keeps_last_request_time_across_holders(phy_home):
    phy_home.mkdir()
    paths = resolve_paths()
    with arxiv_lock(paths) as slot:
        assert slot.last_request_at is None
        slot.mark(1761400000.5)
    with arxiv_lock(paths) as slot:
        assert slot.last_request_at == 1761400000.5
