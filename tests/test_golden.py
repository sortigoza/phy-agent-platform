import hashlib
import shutil
import sqlite3
from datetime import date
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx
from archives import tar_gz
from cards import RECORDED, RECORDED_DRAFT, SEED_LIKE
from typer.testing import CliRunner

from phy import golden
from phy.card import Card
from phy.cli import app
from phy.config import ConfigError, resolve_paths
from phy.verify import facts


def test_manifest_round_trips(phy_home):
    paths = resolve_paths()
    paths.golden.mkdir(parents=True)
    manifest = golden.Manifest(
        version=2,
        papers=[
            golden.Entry(
                arxiv_id="1904.12072",
                version=3,
                sha256="ab" * 32,
                split="dev",
                status="trusted",
                reason="seed",
                expect_in_scope=True,
                added_at=date(2026, 10, 26),
                corrected_by="Saul",
                corrected_at=date(2026, 11, 2),
            )
        ],
    )

    golden.save(paths, manifest)

    assert golden.load(paths) == manifest
    assert "arxiv_id: '1904.12072'" in paths.golden_manifest.read_text()


def test_the_seeded_empty_manifest_loads(phy_home):
    paths = resolve_paths()
    paths.golden.mkdir(parents=True)
    paths.golden_manifest.write_text("# a comment\nversion: 0\npapers: []\n")

    assert golden.load(paths) == golden.Manifest(version=0, papers=[])


def test_an_unknown_key_is_rejected(phy_home):
    paths = resolve_paths()
    paths.golden.mkdir(parents=True)
    paths.golden_manifest.write_text(
        "version: 1\npapers:\n  - arxiv_id: '1904.12072'\n    version: 3\n    sha256: x\n"
        "    split: dev\n    status: placeholder\n    reason: seed\n"
        "    expect_in_scope: true\n    added_at: 2026-10-26\n    corrected_by: null\n"
        "    corrected_at: null\n    notes: hi\n"
    )

    with pytest.raises(ConfigError, match=r"manifest.yaml: papers.0.notes"):
        golden.load(paths)


FIXTURES = Path(__file__).parent / "fixtures" / "oai"
OAI_URL = "https://oaipmh.arxiv.org/oai"
SRC_URL = "https://arxiv.org/src/1904.12072v3"
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
SOURCE = tar_gz({"main.tex": SEED_LIKE.encode()})


@pytest.fixture
def installed(phy_home, monkeypatch):
    (phy_home / "golden").mkdir(parents=True)
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    (phy_home / "golden" / "manifest.yaml").write_bytes(
        (files("phy") / "defaults" / "manifest.yaml").read_bytes()
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("phy.arxiv.time.sleep", lambda _: None)
    return phy_home


@pytest.fixture
def arxiv():
    with respx.mock(assert_all_called=False) as router:
        router.get(OAI_URL).mock(
            return_value=httpx.Response(
                200, content=(FIXTURES / "getrecord_1904.12072.xml").read_bytes()
            )
        )
        router.get(SRC_URL).mock(return_value=httpx.Response(200, content=SOURCE))
        yield router


@pytest.fixture
def messages_api(monkeypatch):
    monkeypatch.setattr("anthropic._base_client.time.sleep", lambda _: None)
    with respx.mock(using="httpx2", assert_all_called=False) as router:
        yield router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=RECORDED))


def phy(*args):
    return CliRunner().invoke(app, list(args))


def rows(phy_home, sql):
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_add_freezes_the_source_and_drafts_a_placeholder(installed, arxiv, messages_api):
    result = phy("golden", "add", "1904.12072", "--split", "dev")

    assert result.exit_code == 0, result.output
    frozen = installed / "golden_sources" / "1904.12072v3"
    assert (frozen / "source.tar.gz").read_bytes() == SOURCE
    assert "Flow-based MCMC" in (frozen / "flattened.txt").read_text()

    manifest = golden.load(resolve_paths())
    assert manifest.version == 1
    [entry] = manifest.papers
    assert (entry.arxiv_id, entry.version) == ("1904.12072", 3)
    assert entry.sha256 == hashlib.sha256(SOURCE).hexdigest()
    assert (entry.split, entry.status, entry.reason) == ("dev", "placeholder", "seed")
    assert entry.expect_in_scope is True
    assert (entry.corrected_by, entry.corrected_at) == (None, None)

    reference = Card.model_validate_json(
        (installed / "golden" / "1904.12072" / "reference.json").read_text()
    )
    assert reference.tldr == RECORDED_DRAFT.tldr
    supports = {f.support for f in facts(reference)}
    assert "supported" in supports  # Verify ran on the frozen text

    assert messages_api.call_count == 1
    assert rows(installed, "SELECT * FROM cards") == []
    assert "git -C" in result.output and "golden/1904.12072/reference.json" in result.output


def placeholder(arxiv_id: str) -> golden.Entry:
    return golden.Entry(
        arxiv_id=arxiv_id,
        version=1,
        sha256="00" * 32,
        split="dev",
        status="placeholder",
        reason="seed",
        expect_in_scope=True,
        added_at=date(2026, 10, 26),
        corrected_by=None,
        corrected_at=None,
    )


def test_a_paper_already_in_the_set_is_refused(installed, arxiv, messages_api):
    assert phy("golden", "add", "1904.12072", "--split", "dev").exit_code == 0

    result = phy("golden", "add", "1904.12072", "--split", "dev")

    assert result.exit_code == 1
    assert golden.load(resolve_paths()).version == 1
    assert (arxiv.calls.call_count, messages_api.call_count) == (2, 1)


def test_a_fifth_dev_placeholder_is_refused_before_any_request(installed, arxiv, messages_api):
    paths = resolve_paths()
    golden.save(
        paths,
        golden.Manifest(version=4, papers=[placeholder(f"2003.0641{i}") for i in range(4)]),
    )

    result = phy("golden", "add", "1904.12072")

    assert result.exit_code == 1
    assert golden.load(paths).version == 4
    assert (arxiv.calls.call_count, messages_api.call_count) == (0, 0)


def test_a_trusted_paper_frees_a_placeholder_slot(installed, arxiv, messages_api):
    paths = resolve_paths()
    trusted = placeholder("2003.06413").model_copy(
        update={"status": "trusted", "corrected_by": "Saul", "corrected_at": date(2026, 11, 2)}
    )
    others = [placeholder(f"1606.0231{i}") for i in range(3)]
    golden.save(paths, golden.Manifest(version=5, papers=[trusted, *others]))

    result = phy("golden", "add", "1904.12072")

    assert result.exit_code == 0, result.output
    assert golden.load(paths).version == 6


def test_held_out_is_rejected_in_m0(installed, arxiv, messages_api):
    result = phy("golden", "add", "1904.12072", "--split", "held_out")

    assert result.exit_code == 1
    assert golden.load(resolve_paths()).papers == []
    assert (arxiv.calls.call_count, messages_api.call_count) == (0, 0)


def test_reason_and_expected_scope_are_recorded(installed, arxiv, messages_api):
    result = phy(
        "golden", "add", "1904.12072", "--reason", "out_of_scope_probe", "--expect-out-of-scope"
    )

    assert result.exit_code == 0, result.output
    [entry] = golden.load(resolve_paths()).papers
    assert (entry.reason, entry.expect_in_scope) == ("out_of_scope_probe", False)


def test_the_golden_call_is_a_traced_golden_run(installed, arxiv, messages_api):
    phy("golden", "add", "1904.12072")

    [run] = rows(installed, "SELECT * FROM runs")
    assert (run["stage"], run["status"], run["arxiv_id"]) == ("golden", "ok", "1904.12072")
    assert run["cost_usd"] > 0
    assert (installed / run["log_path"]).is_file()


def test_check_passes_on_intact_sources(installed, arxiv, messages_api):
    phy("golden", "add", "1904.12072")

    result = phy("golden", "check")

    assert result.exit_code == 0, result.output
    assert golden.check(resolve_paths()) == []


def test_check_reports_a_modified_frozen_source(installed, arxiv, messages_api):
    phy("golden", "add", "1904.12072")
    (installed / "golden_sources" / "1904.12072v3" / "source.tar.gz").write_bytes(b"edited")

    result = phy("golden", "check")

    assert result.exit_code == 1
    assert "1904.12072v3: source.tar.gz sha256" in result.output


def test_check_reports_a_missing_frozen_source(installed, arxiv, messages_api):
    phy("golden", "add", "1904.12072")
    shutil.rmtree(installed / "golden_sources")

    assert golden.check(resolve_paths()) == ["1904.12072v3: frozen source missing"]
