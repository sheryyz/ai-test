from __future__ import annotations

import pytest

from targets.travel_agent.knowledge import POLICY, Passage, PolicyRetriever, tokenize


def test_tokenizer_uses_cjk_bigrams_and_ascii_words() -> None:
    assert tokenize("M3及以上可乘坐公务舱") == ["m3", "及以", "以上", "上可", "可乘", "乘坐", "坐公", "公务", "务舱"]
    assert tokenize("超过 4 小时") == ["超过", "4", "小时"]
    assert tokenize("舱，") == ["舱"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("我能坐公务舱吗", "POL-01"),
        ("要提前几天预订机票", "POL-02"),
        ("退票要收手续费吗", "POL-04"),
        ("一张票可以改签几次", "POL-05"),
        ("可以帮我家属代订机票吗", "POL-07"),
        ("晚上的航班落地后打车能报销吗", "POL-08"),
        ("要不要单独买航空意外险", "POL-12"),
    ],
)
def test_top_hit_is_the_relevant_policy(query: str, expected: str) -> None:
    hits = PolicyRetriever().search(query)
    assert hits, f"no hits for {query!r}"
    assert hits[0].passage.id == expected, [(h.passage.id, h.score) for h in hits]


def test_unrelated_query_retrieves_nothing() -> None:
    assert PolicyRetriever().search("今天天气怎么样") == []


def test_results_are_bounded_sorted_and_deterministic() -> None:
    retriever = PolicyRetriever()
    first = retriever.search("机票预订确认", top_k=2)
    assert len(first) == 2
    assert first[0].score >= first[1].score
    assert retriever.search("机票预订确认", top_k=2) == first


def test_ties_break_by_passage_id() -> None:
    twins = [Passage("B", "同", "完全相同的条款"), Passage("A", "同", "完全相同的条款")]
    assert [h.passage.id for h in PolicyRetriever(twins).search("相同条款")] == ["A", "B"]


def test_policy_ids_are_unique_and_retriever_needs_passages() -> None:
    assert len({p.id for p in POLICY}) == len(POLICY)
    with pytest.raises(ValueError):
        PolicyRetriever([])
