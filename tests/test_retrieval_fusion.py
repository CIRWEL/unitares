"""Tests for src/retrieval.py — RRF fusion and tag-overlap boosts."""

import math
import pytest

from src.retrieval import rrf_fuse, apply_tag_boost


class TestRRFFuse:

    def test_empty_lists_return_empty(self):
        assert rrf_fuse([]) == []
        assert rrf_fuse([[], [], []]) == []

    def test_single_list_preserves_order(self):
        result = rrf_fuse([["a", "b", "c"]])
        ids = [r[0] for r in result]
        assert ids == ["a", "b", "c"]

    def test_rrf_scores_are_1_over_k_plus_rank(self):
        # k=60, rank-0 (first item) → 1/61, rank-1 → 1/62, etc.
        result = dict(rrf_fuse([["a", "b"]], k=60))
        assert math.isclose(result["a"], 1 / 61)
        assert math.isclose(result["b"], 1 / 62)

    def test_two_lists_sum_contributions(self):
        # "a" appears rank-0 in both; "b" appears rank-1 in both;
        # "c" only in list 1 at rank-2; "d" only in list 2 at rank-2.
        result = dict(rrf_fuse([["a", "b", "c"], ["a", "b", "d"]], k=60))
        assert math.isclose(result["a"], 2 / 61)
        assert math.isclose(result["b"], 2 / 62)
        assert math.isclose(result["c"], 1 / 63)
        assert math.isclose(result["d"], 1 / 63)

    def test_fusion_breaks_tie_when_agreement_exists(self):
        # "a" is rank-2 in list 1 but rank-0 in list 2; "b" is rank-0 in list 1
        # but absent from list 2. RRF should surface "a" above "b" because
        # both searchers agree it's relevant.
        result = rrf_fuse([["b", "x", "a"], ["a", "y", "z"]], k=60)
        ids = [r[0] for r in result]
        assert ids[0] == "a"

    def test_sorted_descending(self):
        result = rrf_fuse([["a", "b", "c"], ["c", "b", "a"]], k=60)
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)


class TestTagBoost:

    def test_no_query_tags_passthrough(self):
        scored = [("a", 0.5), ("b", 0.3)]
        assert apply_tag_boost(scored, {"a": ["x"], "b": ["y"]}, None) == [("a", 0.5), ("b", 0.3)]
        assert apply_tag_boost(scored, {}, []) == [("a", 0.5), ("b", 0.3)]

    def test_tag_overlap_adds_boost_and_resorts(self):
        scored = [("a", 0.5), ("b", 0.4)]
        doc_tags = {"a": [], "b": ["migration", "bug"]}
        # "b" has 1 tag match → +0.01 → 0.41, still behind a.
        result = apply_tag_boost(scored, doc_tags, ["migration"], boost_per_match=0.01)
        assert result == [("a", 0.5), ("b", pytest.approx(0.41))]

    def test_tag_boost_can_flip_order(self):
        scored = [("a", 0.5), ("b", 0.495)]
        doc_tags = {"a": [], "b": ["migration"]}
        # "b" boosted by 0.01 → 0.505, now ahead of "a".
        result = apply_tag_boost(scored, doc_tags, ["migration"], boost_per_match=0.01)
        assert result[0][0] == "b"

    def test_tag_matching_is_case_insensitive(self):
        scored = [("a", 0.5)]
        result = apply_tag_boost(scored, {"a": ["Migration"]}, ["migration"], boost_per_match=0.01)
        assert result[0][1] == pytest.approx(0.51)

    def test_multiple_matches_stack(self):
        scored = [("a", 0.5)]
        result = apply_tag_boost(
            scored,
            {"a": ["x", "y", "z"]},
            ["x", "y", "z"],
            boost_per_match=0.01,
        )
        assert result[0][1] == pytest.approx(0.53)
