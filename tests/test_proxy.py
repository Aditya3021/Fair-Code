"""Tests for the opt-in chi-squared proxy hints (needs the scipy extra).

Run from the repo root:  pytest tests/ -q
"""

from pathlib import Path

import pandas as pd
import pytest

from faircode import profile
from faircode.proxy import proxy_hints

pytest.importorskip("scipy", reason="proxy hints need the optional scipy extra")


def test_benefits_denial_native_proxy_summary_is_not_stale():
    # Regression test for #733: the top-of-file proxy summary must keep
    # Native applicants separate from Black applicants, with Native's 20.3%
    # rate preserved instead of the stale ~15% lumping that appears elsewhere.
    source = (Path(__file__).resolve().parents[1] / "Benefits Denial" / "unfair.py").read_text(encoding="utf-8")
    assert "Native applicants are at\n#                   20.3% (~77% of White's rate)." in source
    assert "Native applicants are at\n#                   ~15.5%" not in source


def test_perfect_proxy_is_flagged():
    # occupation is a perfect function of sex -> maximal association.
    df = pd.DataFrame({
        "sex": ["male", "female"] * 100,
        "occupation": ["engineer", "nurse"] * 100,
    })
    dims = profile(df)["dimensions"]
    hints = proxy_hints(df, dims)
    pair = next(h for h in hints
                if {h["a"], h["b"]} == {"sex", "occupation"})
    assert pair["p_value"] < 0.05
    assert pair["cramers_v"] > 0.9   # near-perfect association (Yates-corrected)


def test_held_out_column_catches_proxy_for_a_dropped_attribute():
    # "we dropped race so it's fine": race isn't in the profiled dataframe at
    # all, so it never becomes a dimension - proxy_hints() would otherwise
    # have no way to flag zip_code as a proxy for it (#328).
    race = (["A"] * 100 + ["B"] * 100)
    zip_code = (["111"] * 100 + ["222"] * 100)  # perfectly aligned with race
    df = pd.DataFrame({"zip_code": zip_code, "sex": ["M", "F"] * 100})

    held_out = {"race": pd.Series(race, index=df.index)}
    hints = proxy_hints(df, profile(df)["dimensions"], held_out=held_out)

    pair = next(h for h in hints if {h["a"], h["b"]} == {"zip_code", "race"})
    assert pair["p_value"] < 0.05
    assert pair["cramers_v"] > 0.9


def test_held_out_column_not_flagged_against_an_independent_column():
    # sex cycles every 2 rows, race every 3 - deliberately different periods
    # so the two are independent (verified: no hint), unlike the perfectly-
    # aligned zip_code/race case above.
    df = pd.DataFrame({"sex": ["male", "female"] * 150})
    held_out = {"race": pd.Series((["A", "B", "C"] * 100), index=df.index)}

    hints = proxy_hints(df, profile(df)["dimensions"], held_out=held_out)

    assert not any("race" in (h["a"], h["b"]) for h in hints)


def test_independent_columns_not_flagged():
    # Deterministic independence: sex alternates every row, grp every 3 rows,
    # so the two are (near) independent and should not be flagged.
    df = pd.DataFrame({
        "sex": ["male", "female"] * 150,
        "grp": ["x", "y", "z"] * 100,
    })
    hints = proxy_hints(df, profile(df)["dimensions"])
    assert not any({h["a"], h["b"]} == {"sex", "grp"} for h in hints)


def test_adjust_p_values_bonferroni_and_holm_known_values():
    """#806: hand-computed. Holm on [0.01, 0.04, 0.03], m=3: sorted -> 0.03,
    0.06, 0.04; the running max makes it 0.03, 0.06, 0.06 (input order below)."""
    from faircode.proxy import adjust_p_values

    assert adjust_p_values([0.01, 0.04, 0.03], "bonferroni") == pytest.approx([0.03, 0.12, 0.09])
    assert adjust_p_values([0.01, 0.04, 0.03], "holm") == pytest.approx([0.03, 0.06, 0.06])
    assert adjust_p_values([0.6, 0.9], "bonferroni") == [1.0, 1.0]
    with pytest.raises(ValueError):
        adjust_p_values([0.1], "fdr")


@pytest.mark.parametrize(
    "p_values,method,expected",
    [
        # Empty set of tested pairs (m=0)
        ([], "bonferroni", []),
        ([], "holm", []),
        # Single tested pair (m=1: adjusted equals raw)
        ([0.042], "bonferroni", [0.042]),
        ([0.042], "holm", [0.042]),
        ([0.8], "bonferroni", [0.8]),
        ([0.8], "holm", [0.8]),
        # Ties in Holm: identical p-values break ties stably and monotonicity holds
        ([0.02, 0.02, 0.04], "holm", [0.06, 0.06, 0.06]),
        ([0.05, 0.01, 0.01, 0.03], "holm", [0.06, 0.04, 0.04, 0.06]),
        ([0.03, 0.03], "bonferroni", [0.06, 0.06]),
        ([0.03, 0.03], "holm", [0.06, 0.06]),
        ([0.1, 0.1, 0.1], "holm", [0.3, 0.3, 0.3]),
    ],
)
def test_adjust_p_values_ties_and_edge_cases(p_values, method, expected):
    """#820: covers ties in Holm correction, single tested pair (m=1), and empty input (m=0)."""
    from faircode.proxy import adjust_p_values

    assert adjust_p_values(p_values, method) == pytest.approx(expected)


def test_proxy_hints_zero_testable_pairs_constant_columns():
    """#820: when all columns are constant, contingency tables are < 2x2 and tested pairs is empty."""
    pytest.importorskip("scipy")
    from faircode.proxy import proxy_hints

    df = pd.DataFrame({"col_a": ["const_a"] * 20, "col_b": ["const_b"] * 20, "col_c": ["const_c"] * 20})
    dims = [{"name": c, "kind": "categorical"} for c in df.columns]
    for correction in (None, "bonferroni", "holm"):
        hints = proxy_hints(df, dims, alpha=0.05, correction=correction)
        assert hints == []


def test_proxy_hints_single_testable_pair_adjusted_equals_raw():
    """#820: with exactly one testable pair (m=1), adjusted p-value equals raw p-value."""
    pytest.importorskip("scipy")
    from faircode.proxy import proxy_hints

    df = pd.DataFrame({"col_a": ["m", "f"] * 30, "col_b": ["a", "b"] * 30})
    dims = [{"name": c, "kind": "categorical"} for c in df.columns]
    plain = proxy_hints(df, dims, alpha=1.0)
    assert len(plain) == 1
    raw_p = plain[0]["p_value"]
    for correction in ("bonferroni", "holm"):
        corrected = proxy_hints(df, dims, alpha=1.0, correction=correction)
        assert len(corrected) == 1
        assert corrected[0]["p_adjusted"] == pytest.approx(raw_p)



def _three_dim_frame():
    n = 120
    sex = ["m", "f"] * (n // 2)
    race = ["a" if (i % 2 == 0) == (i % 10 != 0) else "b" for i in range(n)]
    age = [55 if (sex[i] == "m" and i % 3 == 0) or i % 11 == 0 else 25 for i in range(n)]
    return pd.DataFrame({"sex": sex, "race": race, "age": age})


def test_proxy_hints_correction_adds_p_adjusted_and_is_stricter():
    pytest.importorskip("scipy")
    from faircode.detect import detect_columns
    from faircode.proxy import proxy_hints

    df = _three_dim_frame()
    dims = [{"name": d["name"], "kind": d["kind"]} for d in detect_columns(df)]
    plain = proxy_hints(df, dims, alpha=1.0)
    corrected = proxy_hints(df, dims, alpha=1.0, correction="bonferroni")
    assert len(plain) == 3 and "p_adjusted" not in plain[0]
    for h in corrected:
        assert h["p_adjusted"] == pytest.approx(min(1.0, h["p_value"] * 3))
    strict = proxy_hints(df, dims, alpha=0.05, correction="holm")
    assert len(strict) <= len(proxy_hints(df, dims, alpha=0.05))
    with pytest.raises(ValueError, match="correction"):
        proxy_hints(df, dims, correction="nope")
