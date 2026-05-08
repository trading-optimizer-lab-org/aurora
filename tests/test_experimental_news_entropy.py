"""Tests for NewsEntropyRegime detector."""
from __future__ import annotations

import pytest

from quantforge.experimental.news_entropy_regime import (
    NewsEntropyRegime,
    SKLEARN_AVAILABLE,
)


def test_empty_corpus_is_calm():
    det = NewsEntropyRegime()
    res = det.detect([])
    assert res["regime"] == "calm"
    assert res["entropy"] == 0.0
    assert res["n_headlines"] == 0


def test_uniform_repeated_headline_has_low_entropy():
    det = NewsEntropyRegime(calm_max=2.0, volatile_max=4.0)
    headlines = ["fed holds rates steady"] * 30
    res = det.detect(headlines)
    assert res["regime"] == "calm"


def test_diverse_corpus_has_higher_entropy():
    det = NewsEntropyRegime(calm_max=1.0, volatile_max=2.0)
    headlines = [
        "fed cuts rates",
        "bank failures cascade across europe",
        "sovereign debt crisis deepens",
        "oil prices surge on supply shock",
        "currency markets in turmoil",
        "trade war escalates",
        "earnings collapse in tech sector",
        "housing market under severe pressure",
        "credit spreads widen sharply",
        "central banks coordinate emergency response",
    ]
    res = det.detect(headlines)
    # Expect noticeable entropy from a diverse corpus.
    assert res["entropy"] > 1.0
    assert res["regime"] in ("volatile", "crisis")


def test_constructor_validates_thresholds():
    with pytest.raises(ValueError):
        NewsEntropyRegime(calm_max=5.0, volatile_max=4.0)


def test_backend_reflects_sklearn_availability():
    det = NewsEntropyRegime()
    expected = "tfidf" if SKLEARN_AVAILABLE else "bow"
    assert det.backend == expected


def test_detect_filters_non_string_inputs():
    det = NewsEntropyRegime()
    res = det.detect(["news a", None, "", "news b"])
    assert res["n_headlines"] == 2
