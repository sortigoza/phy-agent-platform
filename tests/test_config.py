import shutil
from importlib.resources import files

import pytest

from phy.config import ConfigError, load_config, load_questions, resolve_paths


@pytest.fixture
def paths(phy_home):
    phy_home.mkdir()
    defaults = files("phy") / "defaults"
    paths = resolve_paths()
    shutil.copy(defaults / "config.toml", paths.config_toml)
    shutil.copy(defaults / "questions.yaml", paths.questions_yaml)
    return paths


def test_default_config_loads_quick_start_values(paths):
    config = load_config(paths)
    assert config.watch.backfill_days == 14
    assert config.watch.prefilter["physics:hep-lat"] == "none"
    assert config.watch.prefilter["cs:cs:LG"] == "keywords+physics"
    assert len(config.watch.sets) == 8
    assert config.arxiv.min_interval_s == 3.0
    assert config.filter.model == "claude-haiku-5-5"
    assert config.filter.threshold == 0.5
    assert config.read.model == "claude-sonnet-5-5"
    assert config.read.daily_quota == 8
    assert config.budget.weekly_usd == 20
    assert config.prices["claude-sonnet-5-5"].input == 2.00
    assert config.alerts.candidates_range == (100, 400)
    assert config.ui.port == 8000


def test_default_questions_load_the_four_questions(paths):
    questions = load_questions(paths)
    assert [q.id for q in questions.questions] == ["Q1", "Q2", "Q3", "Q4"]
    assert all(q.keywords for q in questions.questions)
    assert len(questions.scope_notes) == 3
    assert "lattice" in questions.physics_terms


def test_unknown_config_key_is_rejected_naming_it(paths):
    text = paths.config_toml.read_text().replace("[filter]\n", "[filter]\ntreshold = 0.7\n")
    paths.config_toml.write_text(text)
    with pytest.raises(ConfigError, match=r"filter\.treshold"):
        load_config(paths)


def test_invalid_config_value_is_rejected_with_its_path(paths):
    text = paths.config_toml.read_text().replace("backfill_days = 14", 'backfill_days = "two"')
    paths.config_toml.write_text(text)
    with pytest.raises(ConfigError, match=r"config\.toml: watch\.backfill_days"):
        load_config(paths)


def test_arxiv_interval_below_terms_of_use_is_rejected(paths):
    text = paths.config_toml.read_text().replace("min_interval_s = 3.0", "min_interval_s = 1.0")
    paths.config_toml.write_text(text)
    with pytest.raises(ConfigError, match=r"arxiv\.min_interval_s"):
        load_config(paths)


def test_unknown_questions_key_is_rejected_naming_it(paths):
    text = paths.questions_yaml.read_text().replace("    keywords:", "    keywrods:", 1)
    paths.questions_yaml.write_text(text)
    with pytest.raises(ConfigError, match=r"questions\.yaml: questions\.0\.keywrods"):
        load_questions(paths)


def test_missing_config_file_says_to_run_init(paths):
    paths.config_toml.unlink()
    with pytest.raises(ConfigError, match="phy init"):
        load_config(paths)
