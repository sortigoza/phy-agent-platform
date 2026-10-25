"""Where the installation lives and what it is configured to do.

`resolve_paths()` is the only place that builds paths into `$PHY_HOME`; every other module
takes a `Paths`. `load_config()` and `load_questions()` validate the instance config once per
command, so an unknown or invalid key fails before any work.
"""

import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

DEFAULT_HOME = "~/.phy-agent-platform"


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def config_toml(self) -> Path:
        return self.home / "config.toml"

    @property
    def questions_yaml(self) -> Path:
        return self.home / "questions.yaml"

    @property
    def golden(self) -> Path:
        return self.home / "golden"

    @property
    def golden_manifest(self) -> Path:
        return self.golden / "manifest.yaml"

    @property
    def changelog(self) -> Path:
        return self.home / "CHANGELOG.md"

    @property
    def gitignore(self) -> Path:
        return self.home / ".gitignore"

    @property
    def db(self) -> Path:
        return self.home / "phy.db"

    @property
    def phy_lock(self) -> Path:
        return self.home / "phy.lock"

    @property
    def arxiv_lock(self) -> Path:
        return self.home / "arxiv.lock"

    @property
    def app(self) -> Path:
        return self.home / "app"

    @property
    def papers(self) -> Path:
        return self.home / "papers"

    def paper_dir(self, arxiv_id: str, version: int) -> Path:
        """Raw download, unpacked tree and `flattened.txt` of one Paper version."""
        return self.papers / f"{arxiv_id}v{version}"

    def flattened(self, arxiv_id: str, version: int) -> Path:
        return self.paper_dir(arxiv_id, version) / "flattened.txt"

    def source_file(self, arxiv_id: str, version: int, fmt: str) -> Path:
        """The download from `arxiv.org/src/`, named by its detected format (`tar.gz`, ...)."""
        return self.paper_dir(arxiv_id, version) / f"source.{fmt}"

    def source_tree(self, arxiv_id: str, version: int) -> Path:
        """The unpacked LaTeX tree."""
        return self.paper_dir(arxiv_id, version) / "src"

    @property
    def golden_sources(self) -> Path:
        return self.home / "golden_sources"

    @property
    def runs(self) -> Path:
        return self.home / "runs"

    @property
    def git_dir(self) -> Path:
        return self.home / ".git"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    def log_file(self, day: date) -> Path:
        return self.logs / f"phy-{day.isoformat()}.jsonl"

    def log_file_day(self, path: Path) -> date | None:
        """The day of a file made by `log_file`, or None for any other file."""
        stem = path.name.removeprefix("phy-").removesuffix(".jsonl")
        if path.parent != self.logs or stem == path.name:
            return None
        try:
            return date.fromisoformat(stem)
        except ValueError:
            return None


def resolve_paths() -> Paths:
    """`$PHY_HOME` if set, else `~/.phy-agent-platform`."""
    return Paths(home=Path(os.environ.get("PHY_HOME") or DEFAULT_HOME).expanduser())


class ConfigError(Exception):
    """The instance config is missing or invalid. The message names the file and the key."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Prefilter = Literal["none", "keywords", "keywords+physics"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Fraction = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]


class WatchConfig(_Strict):
    backfill_days: PositiveInt
    sets: list[str]
    prefilter: dict[str, Prefilter]

    @model_validator(mode="after")
    def _one_prefilter_per_set(self):
        if set(self.prefilter) != set(self.sets):
            raise ValueError("watch.prefilter must name exactly the sets in watch.sets")
        return self


class ArxivConfig(_Strict):
    min_interval_s: Annotated[float, Field(ge=3.0)]
    max_retries: Annotated[int, Field(ge=1)]  # attempts in all, including the first


class FilterConfig(_Strict):
    model: str
    effort: Effort
    threshold: Fraction
    prompt_version: str


class ReadConfig(_Strict):
    daily_quota: PositiveInt
    always_threshold: Fraction
    weekly_ceiling: PositiveInt
    model: str
    effort: Effort
    prompt_version: str
    recard_stale: Literal["relevant_only", "all", "never"]


class VerifyConfig(_Strict):
    normalize: list[Literal["whitespace", "quotes", "dashes", "latex_spacing"]]


class BudgetConfig(_Strict):
    weekly_usd: Annotated[float, Field(gt=0)]


class Price(_Strict):
    """USD per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float


class AlertsConfig(_Strict):
    candidates_range: tuple[int, int]
    unsupported_rate: Fraction
    review_minutes: float
    minutes_per_relevant: float
    wasted_minutes: float


class RoiConfig(_Strict):
    baseline_minutes: float


class UiConfig(_Strict):
    port: Annotated[int, Field(gt=0, lt=65536)]


class Config(_Strict):
    watch: WatchConfig
    arxiv: ArxivConfig
    filter: FilterConfig
    read: ReadConfig
    verify: VerifyConfig
    budget: BudgetConfig
    prices: dict[str, Price]
    alerts: AlertsConfig
    roi: RoiConfig
    ui: UiConfig

    @model_validator(mode="after")
    def _every_model_has_a_price(self):
        for key, model in [("filter.model", self.filter.model), ("read.model", self.read.model)]:
            if model not in self.prices:
                raise ValueError(f"{key} {model!r} has no prices.{model} table")
        return self


QuestionId = Annotated[str, StringConstraints(pattern=r"^Q[0-9]+$")]


class Question(_Strict):
    id: QuestionId
    title: str
    description: str
    keywords: list[str]
    negative_keywords: list[str]


class Questions(_Strict):
    questions: Annotated[list[Question], Field(min_length=1)]
    physics_terms: list[str]
    negative_keywords: list[str]
    scope_notes: list[str]

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return self


def load_config(paths: Paths) -> Config:
    return _load(paths.config_toml, Config, tomllib.loads)


def load_questions(paths: Paths) -> Questions:
    return _load(paths.questions_yaml, Questions, lambda text: yaml.safe_load(text) or {})


def _load[M: BaseModel](path: Path, model: type[M], parse) -> M:
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"{path} not found; run `phy init` first") from None
    try:
        data = parse(text)
    except (tomllib.TOMLDecodeError, yaml.YAMLError) as e:
        raise ConfigError(f"{path.name}: cannot parse: {e}") from None
    try:
        return model.model_validate(data)
    except ValidationError as e:
        problems = "; ".join(
            f"{path.name}: {'.'.join(map(str, err['loc'])) or '(top level)'}: {err['msg']}"
            for err in e.errors()
        )
        raise ConfigError(problems) from None
