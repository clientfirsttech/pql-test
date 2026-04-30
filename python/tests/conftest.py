"""Shared pytest fixtures for pql-test tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def make_dax_source(func_name: str) -> str:
    """Return a minimal DAX source that contains a FUNCTION declaration."""
    return "\n".join(
        [
            "DEFINE",
            f"\tFUNCTION {func_name} = () =>",
            "\tUNION (",
            f'\t\tPQL.Assert.ShouldEqual("{func_name}: basic check", 1, 1)',
            "\t)",
            "",
            f"EVALUATE {func_name}()",
        ]
    )


@pytest.fixture
def tmp_model(tmp_path: Path):
    """
    Factory fixture that creates a temporary PBIP model directory.

    Usage::

        def test_foo(tmp_model):
            model_dir = tmp_model([
                {"suite_name": "Calculations.DEV", "source": "EVALUATE ROW(...)"},
            ])
            tests = retrieve_tests(model_dir)
            ...
    """

    def _make(dax_tests: list[dict]) -> str:
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True, exist_ok=True)
        for t in dax_tests:
            (dax_dir / f"{t['suite_name']}.Tests.dax").write_text(
                t["source"], encoding="utf-8"
            )
        return str(tmp_path)

    return _make


@pytest.fixture
def sample_model_path() -> str:
    """Absolute path to the SampleModel.SemanticModel directory in examples/."""
    here = Path(__file__).parent
    # Search upward from tests/ to find examples/SampleModel.SemanticModel
    for parent in [here.parent, here.parent.parent]:
        candidate = parent / "examples" / "SampleModel.SemanticModel"
        if candidate.exists():
            return str(candidate)
    pytest.skip("SampleModel.SemanticModel not found — skipping sample model tests")


@pytest.fixture
def rls_model_path() -> str:
    """Absolute path to the RLS_Model.SemanticModel directory in examples/."""
    here = Path(__file__).parent
    for parent in [here.parent, here.parent.parent]:
        candidate = parent / "examples" / "RLS_Model.SemanticModel"
        if candidate.exists():
            return str(candidate)
    pytest.skip("RLS_Model.SemanticModel not found — skipping RLS model tests")


@pytest.fixture
def ols_model_path() -> str:
    """Absolute path to the OLS_Model.SemanticModel directory in examples/."""
    here = Path(__file__).parent
    for parent in [here.parent, here.parent.parent]:
        candidate = parent / "examples" / "OLS_Model.SemanticModel"
        if candidate.exists():
            return str(candidate)
    pytest.skip("OLS_Model.SemanticModel not found — skipping OLS model tests")
