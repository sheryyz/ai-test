"""The LLM halves of the knowledge-base check: test questions with a gold passage, and a
second opinion on conflict candidates. Both are optional and recorded with their model."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from consenttrace.llm.client import ChatClient
from consenttrace.rag.kb_check import KBPassage, bigrams, jaccard

PROMPT_VERSION = "kb-v1"


def _json(text: str | None) -> dict[str, Any]:
    if not text:
        raise ValueError("empty response")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def check_query(query: str, passage: KBPassage, accepted: Sequence[str]) -> list[str]:
    problems = []
    if not 6 <= len(query) <= 40:
        problems.append(f"长度 {len(query)} 不在 6–40 之间")
    if passage.id in query:
        problems.append("问题里出现了条款编号")
    if len(passage.title) >= 3 and passage.title in query:
        problems.append("照抄了条款标题（检索会变得过于容易）")
    if any(jaccard(bigrams(query), bigrams(q)) >= 0.7 for q in accepted):
        problems.append("与已有问题过于相似")
    return problems


def generate_queries(
    client: ChatClient, passages: Sequence[KBPassage], *, per_passage: int = 2
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Employee questions each answered by exactly one passage; checked before they are kept."""
    queries: list[dict[str, Any]] = []
    report: dict[str, Any] = {"rejected": [], "errors": [], "prompt_tokens": 0, "completion_tokens": 0}
    catalogue = "\n".join(f"[{p.id}] {p.title}：{p.text}" for p in passages)
    for p in passages:
        messages = [
            {
                "role": "system",
                "content": (
                    "你在为企业差旅制度知识库构造检索测试题。给定一条目标条款，写出员工可能会问、且只有这条条款能回答的问题。"
                    "要求：口语化，6–40 个字；不要照抄条款标题，不要出现条款编号；各题问法不同。"
                    f'只输出 JSON：{{"queries": ["问题1", ...]}}，共 {per_passage} 题。'
                ),
            },
            {
                "role": "user",
                "content": f"知识库全部条款（供你避开其他条款也能回答的问法）：\n{catalogue}\n\n目标条款：[{p.id}] {p.title}：{p.text}",
            },
        ]
        try:
            turn = client.complete(messages)
            report["prompt_tokens"] += turn.usage.prompt_tokens
            report["completion_tokens"] += turn.usage.completion_tokens
            proposals = _json(turn.content).get("queries") or []
        except Exception as exc:  # recorded; the passage simply gets fewer questions
            report["errors"].append(f"{p.id}: {type(exc).__name__}: {exc}"[:200])
            continue
        kept = 0
        for q in proposals:
            if not isinstance(q, str) or kept == per_passage:
                continue
            q = q.strip()
            problems = check_query(q, p, [x["query"] for x in queries])
            if problems:
                report["rejected"].append({"gold": p.id, "query": q, "problems": problems})
            else:
                queries.append({"query": q, "gold": p.id})
                kept += 1
    return queries, report


def review_pairs(client: ChatClient, pairs: Sequence[tuple[KBPassage, KBPassage]]) -> list[dict[str, Any]]:
    """Ask whether two clauses contradict each other; one call per pair, answers kept verbatim."""
    out = []
    for a, b in pairs:
        messages = [
            {
                "role": "system",
                "content": (
                    "你在审查企业制度知识库的质量。判断两条条款是否互相矛盾：同时遵守两条会导致冲突的要求、数值或结论。"
                    "只是主题相关、互为补充或适用范围不同，都不算矛盾。"
                    '只输出 JSON：{"conflict": true 或 false, "reason": "一句话理由"}'
                ),
            },
            {"role": "user", "content": f"条款 A [{a.id}] {a.title}：{a.text}\n条款 B [{b.id}] {b.title}：{b.text}"},
        ]
        try:
            data = _json(client.complete(messages).content)
            out.append({"pair": [a.id, b.id], "conflict": bool(data.get("conflict")), "reason": str(data.get("reason", ""))})
        except Exception as exc:
            out.append({"pair": [a.id, b.id], "conflict": None, "reason": f"无法判定：{type(exc).__name__}"})
    return out
