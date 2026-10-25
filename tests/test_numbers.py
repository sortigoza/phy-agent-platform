import pytest

from phy.verify import canonicalise, numbers


def parsed(text):
    return [n.text for n in numbers(canonicalise(text, "latex"))]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # plain integers and decimals; a sign is not part of the number
        ("L = 14", ["14"]),
        ("a rate of 0.123", ["0.123"]),
        ("m^2=-4", ["4"]),
        ("a shift of +3.5", ["3.5"]),
        ("L=6--14", ["6", "14"]),
        (r"$L=\{6,8,10,12,14\}$", ["6", "8", "10", "12", "14"]),
        # error bars in parentheses stay one token (and give two numbers)
        ("z = 4.03(6)", ["4.03(6)", "4.03(6)"]),
        (r"$4.03 \pm 0.06$", ["4.03", "0.06"]),
        ("4.03 ± 0.06", ["4.03", "0.06"]),
        # exponents in all three spellings
        ("1.2e-3", ["1.2e-3"]),
        ("6.0E+2", ["6.0E+2"]),
        (r"$1.2\times10^{-3}$", [r"1.2\times10^{-3}"]),
        (r"$1.2 \times 10^{-3}$", [r"1.2 \times 10^{-3}"]),
        (r"$3\times10^5$", [r"3\times10^5"]),
        ("1.2×10⁻³", ["1.2×10⁻³"]),
        ("2.5 × 10¹²", ["2.5 × 10¹²"]),
        ("0.123(4)e-2", ["0.123(4)e-2", "0.123(4)e-2"]),
        # percent and multipliers: the number without its suffix
        (r"50\% and 70\% acceptance", ["50", "70"]),
        ("a 10x speed-up", ["10"]),
        ("a 10× speed-up", ["10"]),
        # glued to an identifier: not numbers
        (r"$\phi^4$ theory", []),
        (r"$\phi^{4}$ theory", []),
        ("costs O(V^2)", []),
        ("m_p and x_1 and x_{12}", []),
        ("a 2D lattice, the 3rd case", []),
        (r"\3 and \\4", []),
        (r"$V^{-2}$, $a^-1$ and $x_{-1}$", []),
        ("SU3 and H2O", []),
        # mixed: the glued ones skipped, the rest kept
        ("keep m_p L ≈ 4 on a 2D lattice", ["4"]),
        (r"$0.3\lesssim z_\mathcal{O}\lesssim 2.0$", ["0.3", "2.0"]),
        (r"$1 / \sqrt{N}$ with $N=10^4$", ["1", "10^4"]),
        (r"$10^{-3}$ and 10⁻³", ["10^{-3}", "10⁻³"]),
        # digits after a control word belong to no identifier
        (r"$4.03\pm0.06$", ["4.03", "0.06"]),
        (r"$(4.03\pm0.06)\times10^{-3}$", ["4.03", "0.06", "10^{-3}"]),
        # words are ignored
        ("one to two GPU-weeks", []),
        # no digits stolen from a longer token
        ("12D", []),
        ("1.25D", []),
        ("version 1.2.3 and .5", ["1.2"]),
    ],
)
def test_extractor(text, expected):
    assert parsed(text) == expected


def one(text):
    (number,) = set(numbers(canonicalise(text, "latex")))
    return number


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("1.2e-3", r"$1.2\times10^{-3}$"),
        ("1.2e-3", "0.0012"),
        ("1.2×10⁻³", "0.0012"),
        ("-4", "4"),
        ("70%", "70"),
        ("6.0E+2", "6.0e2"),
        (r"$10^{-3}$", "1e-3"),
    ],
)
def test_equal_numbers(a, b):
    assert one(a) == one(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [("1.20", "1.2"), ("0.7", "70%"), ("100", "1e2"), ("0.06", "0.6")],
)
def test_different_numbers(a, b):
    assert one(a) != one(b)


@pytest.mark.parametrize("text", ["4.03(6)", r"$4.03 \pm 0.06$"])
def test_error_bars_give_value_and_uncertainty(text):
    assert set(numbers(canonicalise(text, "latex"))) == {one("4.03"), one("0.06")}


def test_uncertainty_scales_with_the_exponent():
    assert set(numbers(canonicalise("1.23(4)e-3", "latex"))) == {one("0.00123"), one("0.00004")}
