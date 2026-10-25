import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest
from typer.testing import CliRunner

from phy.card import Card, CardDraft, Quote
from phy.cli import app
from phy.config import resolve_paths
from phy.locks import phy_lock
from phy.verify import Source, canonicalise, canonicalise_mapped, verify_card

RECORDED = json.loads(
    (
        Path(__file__).parent / "fixtures" / "anthropic" / "read_1904.12072v3_response.json"
    ).read_text()
)
RECORDED_DRAFT = CardDraft.model_validate_json(RECORDED["content"][0]["text"])


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        # cites, refs and labels go, with the ~ before them
        (
            r"local Metropolis~\cite{Wolff1996} and Hybrid Monte Carlo (HMC)~\citep{Duane1987HMC}",
            "local Metropolis and Hybrid Monte Carlo (HMC)",
        ),
        (r"as shown by~\citet[Sec.~2]{Albergo2019}.", "as shown by."),
        (
            r"detailed in Section~\ref{sec:flowMCMC} was applied",
            "detailed in Section was applied",
        ),
        (r"the loss of Eq.~\eqref{eq:loss}\label{eq:x} is", "the loss of Eq. is"),
        # escaped specials become the plain characters
        (
            r"at 50\% and 70\% acceptance, R\&D, costs \$5",
            "at 50% and 70% acceptance, R&D, costs $5",
        ),
        # text-markup macros are unwrapped, nested braces kept
        (
            r"a \emph{normalizing flow} and \textit{exact} \textbf{in the limit {of} } \text{rej}",
            "a normalizing flow and exact in the limit {of} rej",
        ),
        # quotes and dashes to one form
        ("``critical slowing down'' and “exact”", '"critical slowing down" and "exact"'),
        ("`one' and ‘two’", "'one' and 'two'"),
        ("L=6--14, a---b, c–d, e—f", "L=6-14, a-b, c-d, e-f"),
        # small spaces and ties to a space, then whitespace collapsed
        (r"$1.5\,\mathrm{GeV}$ vs.\ HMC\;ok", r"$1.5 \mathrm{GeV}$ vs. HMC ok"),
        ("Fig.~3 shows\n  the\tflow  ", "Fig. 3 shows the flow"),
        # math otherwise as written; case-sensitive
        (r"$0.3\lesssim z_\mathcal{O}\lesssim 2.0$", r"$0.3\lesssim z_\mathcal{O}\lesssim 2.0$"),
        # a line break \\ is not a control space
        (r"a\\ b", r"a\\ b"),
    ],
)
def test_latex_canonicalisation(raw, canonical):
    assert canonicalise(raw, "latex") == canonical


def test_escaped_braces_do_not_close_an_unwrapped_macro():
    assert canonicalise(r"\emph{a \} b} c", "latex") == r"a \} b c"


def test_pdf_canonicalisation_keeps_latex_lookalikes_and_applies_pdf_rules():
    raw = "50\\% eﬃcient soft­hy￾phen “flow” 6–14  scal-\ning"
    assert canonicalise(raw, "pdf") == '50\\% efficient softhyphen "flow" 6-14 scaling'


def test_canonical_text_maps_back_to_the_raw_characters():
    raw = "Metropolis~\\cite{W}  and \\emph{HMC} at 50\\% -- see ``x''"
    text, offsets = canonicalise_mapped(raw, "latex")
    assert text == 'Metropolis and HMC at 50% - see "x"'
    assert len(offsets) == len(text)
    expected = {
        "M": raw.index("M"),
        "H": raw.index("HMC"),
        "%": raw.index("\\%"),
        "-": raw.index("--"),
        '"': raw.index("``"),
    }
    for char, raw_offset in expected.items():
        assert offsets[text.index(char)] == raw_offset
    # every plain character maps to itself
    for i, char in enumerate(text):
        if char.isalnum():
            assert raw[offsets[i]] == char
    assert offsets == sorted(offsets)


PAPER = r"""\documentclass{revtex4}
\newcommand{\ssection}[1]{\section*{#1}\vspace{-1em}}
\newcommand{\paren}[1]{\left(#1\right)}
\begin{document}
\title{Flow-based generative models for Markov chain Monte Carlo in lattice field theory}
We are grateful to the referees for many helpful comments on an earlier draft.
\begin{abstract}
A Markov chain update scheme using a machine-learned flow-based generative model is proposed.
\end{abstract}
\maketitle

\section{Introduction}
Lattice field theory remains the only systematically improvable tool for QCD.

\section{Flow-based MCMC\label{sec:flowMCMC}}
\subsection{Normalizing flows}
Here, a {\it normalizing flow model} is used to define a proposal distribution.
The acceptance probability is
\begin{equation}
  A(\phi, \phi') = \min\paren{1, \frac{p(\phi')}{\tilde{p}(\phi')}}
  \label{eq:acc-rej}
\end{equation}
which makes the Markov chain exact for any choice of model.
\begin{figure*}
\includegraphics{autocorr.pdf}
\caption{Integrated autocorrelation time against lattice size for every sampler.}
\label{fig:compare_autocorr}
\end{figure*}

\ssection{Application to $\phi^4$ theory}
All parameters were chosen to lie in the symmetric phase.

The flow was trained with the shifted KL loss of Eq.~\eqref{eq:loss} as usual.
\appendix
\section{Training}
\subsection{Hyperparameters and their tuning}
All models were trained using one to two GPU-weeks on one node.
\end{document}
"""


def check(quote, raw=PAPER, source_type="latex"):
    return Source(raw, source_type).check(quote)


def test_a_verbatim_quote_is_found_with_its_section_and_match_count():
    result = check("Lattice field theory remains the only systematically improvable tool")
    assert (result.found, result.loc, result.match_count) == (True, 'Sec. "Introduction"', 1)


def test_a_quote_differing_only_in_canonical_form_is_found():
    result = check("The flow was trained with the shifted KL loss of Eq. as usual.")
    assert result.found
    assert result.loc == r'Sec. "Application to $\phi^4$ theory"'


@pytest.mark.parametrize(
    "quote",
    [
        "All parameters were chosen",  # 4 words
        " ".join(["word"] * 61),
        "Here, a {\\it normalizing flow model} ... proposal distribution.",
        "Here, a {\\it normalizing flow model} is used … distribution.",
        "the symmetric phase. The flow was trained with",  # across a blank line
        r"\subsection{Normalizing flows} Here, a {\it normalizing flow model}",  # across a heading
        "This sentence is nowhere in the paper at all.",
    ],
)
def test_quotes_breaking_a_shape_rule_or_absent_are_not_found(quote):
    raw = PAPER + "\n" + " ".join(["word"] * 61) + "\n"
    assert not check(quote, raw).found


def test_repeated_quote_counts_every_match_and_locates_the_first():
    raw = PAPER.replace(
        r"\end{document}", "Lattice field theory remains the only systematically improvable tool.\n"
    )
    result = check("Lattice field theory remains the only systematically improvable tool", raw)
    assert (result.loc, result.match_count) == ('Sec. "Introduction"', 2)


@pytest.mark.parametrize(
    ("quote", "loc"),
    [
        ("We are grateful to the referees for many helpful comments", "front matter"),
        ("A Markov chain update scheme using a machine-learned", "Abstract"),
        (
            "a {\\it normalizing flow model} is used to define",
            'Sec. "Normalizing flows"',
        ),
        (
            r"A(\phi, \phi') = \min\paren{1, \frac{p(\phi')}{\tilde{p}(\phi')}}",
            'Sec. "Normalizing flows" · eq:acc-rej',
        ),
        (
            "Integrated autocorrelation time against lattice size for every sampler.",
            'Sec. "Normalizing flows" · fig:compare_autocorr',
        ),
        (
            "All parameters were chosen to lie in the symmetric phase.",
            r'Sec. "Application to $\phi^4$ theory"',
        ),
        (
            "All models were trained using one to two GPU-weeks",
            'App. "Hyperparameters and their tuning"',
        ),
    ],
)
def test_loc_is_the_innermost_heading_plus_the_enclosing_label(quote, loc):
    result = check(quote)
    assert result.found
    assert result.loc == loc


def test_a_heading_with_a_label_inside_is_shown_without_it():
    raw = PAPER.replace(
        r"\section{Introduction}", r"\section{Intro \emph{duction}\label{sec:intro}}"
    )
    assert check("Lattice field theory remains the only", raw).loc == r'Sec. "Intro \emph{duction}"'


def test_a_row_of_a_multi_label_environment_gets_its_own_label():
    raw = PAPER.replace(
        r"\end{document}",
        "\\begin{align}\n  a &= b + c \\label{eq:first} \\\\\n"
        "  d &= e + f + g + h \\label{eq:second}\n\\end{align}\n",
    )
    assert (
        check("d &= e + f + g + h", raw).loc
        == 'App. "Hyperparameters and their tuning" · eq:second'
    )
    assert check("a &= b + c", raw).loc.endswith("· eq:first")


def test_a_heading_macro_made_with_let_is_a_heading():
    raw = PAPER.replace(r"\begin{document}", "\\let\\lsec\\section\n\\begin{document}")
    raw = raw.replace(r"\section{Introduction}", r"\lsec{Introduction}")
    assert check("Lattice field theory remains the only", raw).loc == 'Sec. "Introduction"'


def test_a_source_without_begin_document_still_finds_macro_headings():
    raw = (
        "\\newcommand{\\ssection}[1]{\\section*{#1}}\n"
        "Some opening words of the fragment here.\n"
        "\\ssection{Results}\nThe flow was exact for every model we tried.\n"
    )
    assert check("Some opening words of the fragment", raw).loc == "front matter"
    assert check("The flow was exact for every model", raw).loc == 'Sec. "Results"'


def test_pdf_loc_is_the_page_counted_from_form_feeds():
    raw = "Title page text here.\fThe flow is exact\nfor any model we tried.\fLast page words."
    result = check("The flow is exact for any model", raw, "pdf")
    assert (result.found, result.loc) == (True, "p. 2")


# Synthetic flattened text holding the recorded draft's quotes, in raw forms that differ from
# the quotes only canonically. One quote is split by a blank line, and one is missing.
SEED_LIKE = r"""\documentclass[aps,prd]{revtex4-1}
\begin{document}
\begin{abstract}
A key feature of the approach is that models trained to a fixed acceptance rate do not
experience critical slowing down in the sampling stage.
\end{abstract}

\section{Introduction}
Here, a {\it normalizing flow model} is used to define a proposal distribution
$\tilde{p}(\phi)$ for a generative Metropolis-Hastings algorithm.

\section{Flow-based MCMC\label{sec:flowMCMC}}
We assume the Markov chain is initialized with a sample from the stationary distribution
$p(\phi)$ throughout.

\section{Application to $\phi^4$ theory}
\subsection{Results}
In this work, the flow-based MCMC algorithm detailed in Section~\ref{sec:flowMCMC} was
applied to $\phi^4$ theory in two dimensions with $L=\{6,8,10,12,14\}$ lattice sites in each
dimension. For simplicity in this initial work, all parameters were chosen to lie in the
symmetric phase. We compare against HMC as well as standard local Metropolis~\cite{Wolff1996}
and Hybrid Monte Carlo (HMC)~\citep{Duane1987HMC} algorithms at matched parameters.

For all observables, the values computed using the flow-based MCMC ensembles are consistent
within statistical uncertainties with those computed using the standard methods.
In each case, the critical exponent was $0.3\lesssim z_\mathcal{O}\lesssim 2.0$.
In comparison, for the flow-based MCMC ensembles at a fixed acceptance, the critical exponent

was found to be consistent with zero, with the autocorrelation time observable-independent.
Moreover, Figure~\ref{fig:errorscaling} shows that the statistical uncertainties of the
observables scale as $1 / \sqrt{N}$ with the number of samples $N$, as expected for
decorrelated samples. Since the the mean acceptance rate was used as the stopping criterion
for training these models, we compare at fixed acceptance.

\section{Conclusions}
In this work, all models were trained using one to two GPU-weeks, with the larger lattices
incurring the most computational cost. However, the efficiency with which the training step
of this approach can be scaled to larger model sizes, and to more complicated theories such
as QCD, remains to be studied. This asymptotic scaling is a result of the simple model
architecture used in this proof-of-principle study.
\end{document}
"""


def test_recorded_draft_gets_the_expected_support():
    verified = verify_card(RECORDED_DRAFT, Source(SEED_LIKE, "latex"))
    card = verified.card
    assert [f.support for f in card.key_results] == [
        "supported",
        "unsupported",  # split by a blank line
        "supported",
        "supported",
        "supported",
    ]
    assert [f.support for f in card.assumptions] == ["supported", "supported", "inferred"]
    assert card.system.support == "supported"
    assert card.method.support == "inferred"
    assert card.baselines.support == "supported"
    assert card.claimed_advance.support == "supported"
    assert card.code_data is None
    assert [f.support for f in card.limitations_stated] == [
        "supported",
        "unsupported",  # not in the source
        "supported",
    ]
    assert (verified.unsupported_count, verified.inferred_count) == (2, 2)
    assert card.system.evidence[0].loc == 'Sec. "Results"'
    assert card.claimed_advance.evidence[0].loc == "Abstract"
    assert card.method.evidence[0].loc == 'Sec. "Introduction"'
    assert card.key_results[0].evidence[0].match_count == 1
    assert card.limitations_stated[1].evidence[0].found is False
    assert card.limitations_stated[1].evidence[0].loc is None


def test_every_quote_on_a_fact_must_be_found():
    good = Quote(quote="For simplicity in this initial work, all parameters were chosen")
    bad = Quote(quote="For simplicity, all parameters were chosen in the symmetric phase.")
    first, second = RECORDED_DRAFT.assumptions[:2]
    assumptions = [
        first.model_copy(update={"evidence": [good, bad]}),
        second.model_copy(update={"evidence": [good]}),
    ]
    # The schema forbids a Fact with no Evidence; Verify still treats one as unsupported.
    system = RECORDED_DRAFT.system.model_copy(update={"evidence": []})
    draft = RECORDED_DRAFT.model_copy(update={"assumptions": assumptions, "system": system})
    card = verify_card(draft, Source(SEED_LIKE, "latex")).card
    assert [e.found for e in card.assumptions[0].evidence] == [True, False]
    assert card.assumptions[0].support == "unsupported"
    assert card.assumptions[1].support == "supported"
    assert card.system.support == "unsupported"


@pytest.fixture
def installed(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    return phy_home


def add_draft(phy_home, arxiv_id, version, flattened, *, source_type="latex", status="draft"):
    """A Paper version with its `flattened.txt` and the recorded draft as its Card."""
    from phy import db

    db.connect(phy_home / "phy.db").close()  # migrate
    conn = sqlite3.connect(phy_home / "phy.db")
    at = "2026-10-25T00:00:00+00:00"
    run_id = f"read-{arxiv_id}v{version}"
    with conn:
        conn.execute(
            "INSERT INTO papers (arxiv_id, latest_version, title, authors, abstract, categories,"
            " primary_category, sets, first_seen_at, updated_at) VALUES"
            " (?, ?, 'T', 'A. Author', 'abs', 'hep-lat', 'hep-lat', 'physics:hep-lat', ?, ?)"
            " ON CONFLICT DO UPDATE SET latest_version = excluded.latest_version",
            (arxiv_id, version, at, at),
        )
        conn.execute(
            "INSERT INTO paper_versions (arxiv_id, version, submitted_at, first_seen_datestamp,"
            " source_type) VALUES (?, ?, ?, '2026-10-25', ?)",
            (arxiv_id, version, at, source_type),
        )
        conn.execute(
            "INSERT INTO runs (id, stage, arxiv_id, status, started_at)"
            " VALUES (?, 'read', ?, 'ok', ?)",
            (run_id, arxiv_id, at),
        )
        conn.execute(
            "INSERT INTO cards (arxiv_id, version, card_json, status, model, prompt_version,"
            " schema_version, run_id, created_at, updated_at) VALUES (?, ?, ?, ?,"
            " 'claude-sonnet-5-5', 'v2', 'card/v1', ?, ?, ?)",
            (arxiv_id, version, RECORDED_DRAFT.model_dump_json(), status, run_id, at, at),
        )
    conn.close()
    path = phy_home / "papers" / f"{arxiv_id}v{version}" / "flattened.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(flattened)


def phy(*args):
    return CliRunner().invoke(app, list(args))


def rows(phy_home, sql):
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def card_row(phy_home, arxiv_id):
    [row] = rows(phy_home, f"SELECT * FROM cards WHERE arxiv_id = '{arxiv_id}'")
    return row


def card_of(phy_home, arxiv_id):
    return Card.model_validate_json(card_row(phy_home, arxiv_id)["card_json"])


def test_verify_catches_up_on_every_draft_card(installed):
    add_draft(installed, "1904.12072", 3, SEED_LIKE)
    add_draft(installed, "2003.06413", 1, "Nothing quoted here.")
    add_draft(installed, "1606.02318", 2, "Old text.", status="verified")

    result = phy("verify")

    assert result.exit_code == 0, result.output
    row, card = card_row(installed, "1904.12072"), card_of(installed, "1904.12072")
    assert row["status"] == "verified"
    assert (row["unsupported_count"], row["inferred_count"]) == (2, 2)
    assert card.system.support == "supported"
    assert card.system.evidence[0].loc == 'Sec. "Results"'
    row = card_row(installed, "2003.06413")
    assert row["status"] == "verified"
    assert row["unsupported_count"] == 15
    already = card_row(installed, "1606.02318")
    assert already["unsupported_count"] is None  # left alone
    [run] = rows(installed, "SELECT * FROM runs WHERE stage = 'verify'")
    assert run["status"] == "ok"
    assert "2 verified" in result.output


def test_pdf_cards_are_located_by_page(installed):
    pdf = SEED_LIKE.replace(r"\section{Conclusions}", "\f")
    add_draft(installed, "1904.12072", 3, pdf, source_type="pdf")

    assert phy("verify").exit_code == 0

    card = card_of(installed, "1904.12072")
    assert card.key_results[4].evidence[0].loc == "p. 2"


def test_verify_paper_skips_a_verified_card_unless_forced(installed):
    add_draft(installed, "1904.12072", 3, "Nothing quoted here.")
    assert phy("verify", "--paper", "1904.12072").exit_code == 0
    (installed / "papers" / "1904.12072v3" / "flattened.txt").write_text(SEED_LIKE)

    result = phy("verify", "--paper", "1904.12072")
    assert result.exit_code == 0, result.output
    assert "--force" in result.output
    assert card_row(installed, "1904.12072")["unsupported_count"] == 15

    result = phy("verify", "--paper", "1904.12072", "--force")
    assert result.exit_code == 0, result.output
    row = card_row(installed, "1904.12072")
    assert (row["status"], row["unsupported_count"]) == ("verified", 2)


def test_force_keeps_a_reviewed_card_reviewed(installed):
    add_draft(installed, "1904.12072", 3, SEED_LIKE, status="reviewed")

    assert phy("verify", "--paper", "1904.12072", "--force").exit_code == 0

    row = card_row(installed, "1904.12072")
    assert (row["status"], row["unsupported_count"]) == ("reviewed", 2)


def test_force_needs_a_paper(installed):
    assert phy("verify", "--force").exit_code != 0


def test_a_paper_without_a_card_fails(installed):
    add_draft(installed, "1904.12072", 3, SEED_LIKE)
    assert phy("verify", "--paper", "2003.06413").exit_code == 1


def test_a_card_whose_text_is_missing_fails_the_run_but_not_the_others(installed):
    add_draft(installed, "1904.12072", 3, SEED_LIKE)
    add_draft(installed, "2003.06413", 1, "Nothing quoted here.")
    (installed / "papers" / "2003.06413v1" / "flattened.txt").unlink()

    result = phy("verify")

    assert result.exit_code == 1
    assert card_row(installed, "1904.12072")["status"] == "verified"
    assert card_row(installed, "2003.06413")["status"] == "draft"
    [run] = rows(installed, "SELECT * FROM runs WHERE stage = 'verify'")
    assert run["status"] == "failed"
    assert "2003.06413" in run["error"]


def test_held_phy_lock_makes_verify_exit_zero_without_work(installed):
    add_draft(installed, "1904.12072", 3, SEED_LIKE)
    with phy_lock(resolve_paths()):
        result = phy("verify")
    assert result.exit_code == 0
    assert card_row(installed, "1904.12072")["status"] == "draft"


def test_a_card_that_does_not_validate_fails_without_echoing_its_quotes(installed):
    add_draft(installed, "1904.12072", 3, SEED_LIKE)
    conn = sqlite3.connect(installed / "phy.db")
    with conn:
        broken = json.loads(RECORDED_DRAFT.model_dump_json())
        del broken["tldr"]
        conn.execute("UPDATE cards SET card_json = ?", (json.dumps(broken),))
    conn.close()

    result = phy("verify")

    assert result.exit_code == 1
    [run] = rows(installed, "SELECT * FROM runs WHERE stage = 'verify'")
    assert "tldr" in run["error"]
    assert "For all observables" not in run["error"]
