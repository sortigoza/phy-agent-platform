from phy.ui.latex import preamble_macros, tex_html

PREAMBLE = r"""\documentclass[aps,prd]{revtex4-1}
\usepackage{amsmath}
\newcommand{\paren}[1]{\left(#1\right)}
\newcommand*{\netp}{\tilde{p}_f}
\renewcommand\sq[1]{\left[#1\right]}
\providecommand{\expt}[1]{\underset{#1}{\mathbb{E}}}
\def\half{\frac{1}{2}}
\newcommand{\opt}[2][x]{#1^{#2}}
\newcommand{\braced}{\{a\}}
\begin{document}
\newcommand{\late}{body only}
\end{document}
"""


def test_preamble_macros_become_katex_macros():
    assert preamble_macros(PREAMBLE) == {
        r"\paren": r"\left(#1\right)",
        r"\netp": r"\tilde{p}_f",
        r"\sq": r"\left[#1\right]",
        r"\expt": r"\underset{#1}{\mathbb{E}}",
        r"\half": r"\frac{1}{2}",
        r"\braced": r"\{a\}",
    }


def test_a_fragment_without_begin_document_is_all_preamble():
    assert preamble_macros(r"\newcommand{\a}{b}") == {r"\a": "b"}


def test_text_markup_is_cleaned_and_math_left_for_katex():
    html = tex_html(r"a {\it normalizing flow} and \emph{HMC}~\cite{Duane} --- $x<1$ ``ok''")
    assert html.startswith("a <i>normalizing flow</i> and <i>HMC</i> ")
    assert 'class="ref"' in html
    assert "— $x&lt;1$ “ok”" in html


def test_unknown_commands_stay_raw():
    assert tex_html(r"\weird{x} <b>") == r"\weird{x} &lt;b&gt;"
