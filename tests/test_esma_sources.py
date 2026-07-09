from __future__ import annotations

from src.esma_sources import parse_facet_pairs


def test_parse_facet_pairs_converts_flat_solr_list():
    raw = ["Non liquid", 1177, "Liquid", 153]
    assert parse_facet_pairs(raw) == [("Non liquid", 1177), ("Liquid", 153)]


def test_parse_facet_pairs_drops_zero_counts():
    raw = ["XATH", 5, "XPAR", 0]
    assert parse_facet_pairs(raw) == [("XATH", 5)]


def test_parse_facet_pairs_handles_empty():
    assert parse_facet_pairs([]) == []
