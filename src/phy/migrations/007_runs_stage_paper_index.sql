-- For the unretried-failure check (a later `ok` run of the same Stage and Paper) behind the
-- Stage failures tile and `phy status`. `runs (started_at)` is already indexed by 001.

CREATE INDEX runs_stage_arxiv_id_started_at ON runs (stage, arxiv_id, started_at);
