"""`phy daily` (SPEC §5): Watch → Filter → Read → Verify, unattended.

Each Stage is its own run with its own run_id. A Stage that fails is logged once at ERROR and
the later Stages still run on what exists; every Stage catches up on the next run. The command
fails only for a crash: invalid config, or a Stage raising something other than its known
errors (a bug), which is logged with its traceback after the later Stages have run.
"""

from dataclasses import dataclass, field, replace

import structlog

from phy import filter as filter_stage
from phy import verify as verify_stage
from phy import watch as watch_stage
from phy.ctx import Ctx, new_run_id
from phy.log import log_failure
from phy.read import stage as read_stage

log = structlog.get_logger()

STAGES = [
    ("watch", watch_stage.run, watch_stage.ERRORS),
    ("filter", filter_stage.run, filter_stage.ERRORS),
    ("read", read_stage.run_selected, read_stage.ERRORS),
    ("verify", verify_stage.run, verify_stage.ERRORS),
]


@dataclass
class Ran:
    failed: list[str] = field(default_factory=list)  # Stages that failed, crashed ones included
    crashed: list[str] = field(default_factory=list)  # Stages that raised something unexpected


def run(ctx: Ctx) -> Ran:
    """Run every Stage in order, whatever happens to the earlier ones."""
    ran = Ran()
    for name, stage, errors in STAGES:
        try:
            stage(replace(ctx, run_id=new_run_id()))
        except Exception as e:
            ran.failed.append(name)
            if not isinstance(e, errors):
                ran.crashed.append(name)
            log_failure(log, "daily.stage_failed", e, errors, stage=name)
    log.info("daily.finished", failed=ran.failed)
    return ran
