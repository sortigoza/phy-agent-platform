import json

import pytest

from phy.read.flatten import NoMainFile, flatten


def tree(root, files: dict[str, str]):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def doc(body: str, preamble: str = "") -> str:
    return f"\\documentclass{{article}}\n{preamble}\\begin{{document}}\n{body}\n\\end{{document}}\n"


def test_main_file_is_the_one_with_an_uncommented_documentclass(tmp_path):
    tree(
        tmp_path,
        {
            "notes.tex": "% \\documentclass{article}\nscratch notes\n",
            "paper.tex": doc("The paper."),
        },
    )
    out = flatten(tmp_path)
    assert "The paper." in out
    assert "scratch notes" not in out


def test_00readme_json_toplevel_wins_over_documentclass(tmp_path):
    tree(
        tmp_path,
        {
            "00README.json": json.dumps(
                {"sources": [{"filename": "real.tex", "usage": "toplevel"}]}
            ),
            "aaa-big-decoy.tex": doc("Decoy. " * 100),
            "real.tex": doc("Real paper."),
        },
    )
    out = flatten(tmp_path)
    assert "Real paper." in out
    assert "Decoy." not in out


def test_legacy_00readme_toplevel_line_wins(tmp_path):
    tree(
        tmp_path,
        {
            "00README.XXX": "real.tex toplevel\nfigs.tex ignore\n",
            "aaa-decoy.tex": doc("Decoy."),
            "real.tex": doc("Real paper."),
        },
    )
    assert "Real paper." in flatten(tmp_path)


def test_no_main_file_raises(tmp_path):
    tree(tmp_path, {"fragment.tex": "just a section\n"})
    with pytest.raises(NoMainFile):
        flatten(tmp_path)


def test_input_and_include_are_inlined_recursively(tmp_path):
    tree(
        tmp_path,
        {
            "main.tex": doc("\\input{sections/a}\n\\include{c}"),
            "sections/a.tex": "A starts.\n\\input{sections/b.tex}\nA ends.\n",
            "sections/b.tex": "B text.\n",
            "c.tex": "C text.\n",
        },
    )
    out = flatten(tmp_path)
    assert "A starts.\nB text.\n" in out
    assert "C text." in out
    assert "\\input" not in out
    assert "\\include{" not in out


def test_nested_brace_less_input(tmp_path):
    tree(
        tmp_path,
        {
            "main.tex": doc("\\input sections/method.tex\nAfter."),
            "sections/method.tex": "Method.\n\\input sections/detail\n",
            "sections/detail.tex": "Detail.\n",
        },
    )
    out = flatten(tmp_path)
    assert "Method.\nDetail." in out
    assert "After." in out


def test_includegraphics_is_not_an_include(tmp_path):
    tree(tmp_path, {"main.tex": doc("\\includegraphics{fig1}")})
    assert "\\includegraphics{fig1}" in flatten(tmp_path)


def test_missing_input_is_left_in_place(tmp_path):
    tree(tmp_path, {"main.tex": doc("\\input{nowhere}\nStill here.")})
    out = flatten(tmp_path)
    assert "\\input{nowhere}" in out
    assert "Still here." in out


def test_an_input_cycle_stops(tmp_path):
    tree(
        tmp_path,
        {"main.tex": doc("\\input{a}"), "a.tex": "A.\n\\input{b}\n", "b.tex": "B.\n\\input{a}\n"},
    )
    out = flatten(tmp_path)
    assert out.count("A.") == 1
    assert out.count("B.") == 1


def test_percent_comments_are_stripped_but_escaped_percent_is_kept(tmp_path):
    tree(
        tmp_path,
        {
            "main.tex": doc(
                "% a whole-line comment\n"
                "Accuracy is 68\\% here. % trailing remark\n"
                "Line break\\\\% comment after a break\n"
                "\\input{a} % commented \\input{b}\n"
                "% \\input{b}"
            ),
            "a.tex": "A.\n",
            "b.tex": "SHOULD NOT APPEAR\n",
        },
    )
    out = flatten(tmp_path)
    assert "whole-line comment" not in out
    assert "Accuracy is 68\\% here." in out
    assert "trailing remark" not in out
    assert "Line break\\\\\n" in out
    assert "comment after a break" not in out
    assert "SHOULD NOT APPEAR" not in out


def test_comments_in_inputs_are_stripped(tmp_path):
    tree(tmp_path, {"main.tex": doc("\\input{a}"), "a.tex": "Kept. % dropped\n"})
    out = flatten(tmp_path)
    assert "Kept." in out
    assert "dropped" not in out


def test_comment_environment_is_dropped(tmp_path):
    tree(
        tmp_path,
        {"main.tex": doc("Before.\n\\begin{comment}\nOld draft.\n\\end{comment}\nAfter.")},
    )
    out = flatten(tmp_path)
    assert "Old draft." not in out
    assert "Before." in out
    assert "After." in out


def test_iffalse_block_is_dropped_including_nested_conditionals(tmp_path):
    tree(
        tmp_path,
        {
            "main.tex": doc(
                "Before.\n\\iffalse\nHidden \\ifdefined\\foo nested\\fi still hidden.\n\\fi\n"
                "Middle $a \\iff b$.\n\\iffalse Gone \\else Shown \\fi\nAfter."
            )
        },
    )
    out = flatten(tmp_path)
    assert "Hidden" not in out
    assert "still hidden" not in out
    assert "Gone" not in out
    assert "Shown" in out
    assert "Middle $a \\iff b$." in out
    assert "Before." in out
    assert "After." in out


def test_text_after_end_document_is_dropped(tmp_path):
    tree(tmp_path, {"main.tex": doc("Body.") + "Trailing junk.\n"})
    out = flatten(tmp_path)
    assert out.rstrip().endswith("\\end{document}")
    assert "Trailing junk." not in out


def test_thebibliography_is_dropped_but_the_appendix_after_it_kept(tmp_path):
    tree(
        tmp_path,
        {
            "main.tex": doc(
                "Body cites \\cite{a}.\n"
                "\\begin{thebibliography}{9}\n\\bibitem{a} A. Author, Journal.\n"
                "\\end{thebibliography}\n"
                "\\appendix\n\\section{Proof}\\label{app:proof}\nThe proof."
            )
        },
    )
    out = flatten(tmp_path)
    assert "A. Author" not in out
    assert "thebibliography" not in out
    assert "\\cite{a}" in out
    assert "\\section{Proof}\\label{app:proof}\nThe proof." in out


def test_bibliography_commands_are_dropped_and_the_appendix_after_them_kept(tmp_path):
    tree(
        tmp_path,
        {
            "main.tex": doc(
                "Body.\n\\bibliographystyle{apsrev4-1}\n\\bibliography{refs,more}\n"
                "\\appendix\n\\section{Extra}\nAppendix text."
            )
        },
    )
    out = flatten(tmp_path)
    assert "\\bibliography" not in out
    assert "Appendix text." in out


def test_macros_labels_refs_and_math_are_kept_verbatim(tmp_path):
    body = "We find $\\Uone$ with $10^{6}$ samples, see Eq.~\\eqref{eq:1} and \\cite{x}."
    tree(tmp_path, {"main.tex": doc(body, preamble="\\newcommand{\\Uone}{U(1)}\n")})
    out = flatten(tmp_path)
    assert body in out
    assert "\\newcommand{\\Uone}{U(1)}" in out


def test_latin1_source_is_read(tmp_path):
    (tmp_path / "main.tex").write_bytes(doc("Schr\xf6dinger.").encode("latin-1"))
    assert "Schrödinger." in flatten(tmp_path)
