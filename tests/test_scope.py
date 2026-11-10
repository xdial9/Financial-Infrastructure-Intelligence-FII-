"""Tests for FII scope normalization."""

import pytest

from fii.core.scope import ScopeError, normalize_domain


def test_normalize_domain_lowercases_and_removes_trailing_dot() -> None:
    assert normalize_domain("WWW.Example.Invalid.") == "www.example.invalid"


def test_normalize_domain_converts_idn_to_ascii() -> None:
    assert normalize_domain("bücher.example") == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://example.invalid",
        "example.invalid/path",
        "user@example.invalid",
        "127.0.0.1",
        "example..invalid",
        "-bad.example",
    ],
)
def test_normalize_domain_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ScopeError):
        normalize_domain(value)
