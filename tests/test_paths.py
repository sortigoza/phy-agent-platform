from pathlib import Path

from phy.config import resolve_paths


def test_phy_home_env_override(phy_home):
    paths = resolve_paths()
    assert paths.home == phy_home
    assert paths.config_toml == phy_home / "config.toml"
    assert paths.questions_yaml == phy_home / "questions.yaml"
    assert paths.golden_manifest == phy_home / "golden" / "manifest.yaml"
    assert paths.changelog == phy_home / "CHANGELOG.md"
    assert paths.db == phy_home / "phy.db"
    assert paths.phy_lock == phy_home / "phy.lock"
    assert paths.arxiv_lock == phy_home / "arxiv.lock"
    assert paths.papers == phy_home / "papers"
    assert paths.golden_sources == phy_home / "golden_sources"
    assert paths.runs == phy_home / "runs"
    assert paths.logs == phy_home / "logs"
    assert paths.app == phy_home / "app"


def test_phy_home_defaults_to_dot_dir_in_home(monkeypatch, tmp_path):
    monkeypatch.delenv("PHY_HOME")
    assert resolve_paths().home == Path(tmp_path / "user-home" / ".phy-agent-platform")
