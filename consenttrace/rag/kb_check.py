"""Knowledge-base health check for RAG agents: errors, redundancy, conflicts, retrieval quality.

Works on any list of passages {id, title, text} and any search function (query, k) -> ranked
ids; ConsentTrace gets both from the agent under test (its own retriever), so what is
measured is the agent's real retrieval, not a stand-in. Everything here is deterministic.
Conflict detection proposes candidates by rule (same topic, same unit, different number; or
"must" against "need not" on the same subject); an optional LLM review (consenttrace.rag.llm)
confirms or dismisses them, and both verdicts are reported.

The checker is itself tested: `seed_faults` plants known duplicates, numeric conflicts,
dangling references and missing titles in a copy of the base, and the report says how many
of them were found.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

Search = Callable[[str, int], list[str]]

_CJK_RUN = re.compile(r"[一-鿿]+|[a-z0-9]+")
_NUMBER_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(个工作日|工作日|小时|天|%|元|次|公里|人|岁|分钟)")
_REFERENCE = re.compile(r"\b([A-Z]{2,5}-\d{1,4})\b")
MUST = ("必须", "须", "应当", "不得", "禁止")
NEED_NOT = ("无需", "不需要", "不必", "可直接", "跳过", "视为", "视作", "默认授权")
STOP = frozenset({"员工", "助手", "差旅", "公司", "本人", "以上", "进行", "相关", "须", "的", "或", "及", "可", "等", "按", "前"})
MUST_SCOPE, WAIVE_SCOPE = 24, 12  # characters after the cue that say what is required / waived


@dataclass(frozen=True)
class KBPassage:
    id: str
    title: str
    text: str


@dataclass
class Issue:
    kind: str  # error | redundancy | conflict
    rule: str
    passages: list[str]
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] | None = None  # the LLM review of a candidate, when run


def bigrams(text: str) -> set[str]:
    out: set[str] = set()
    for run in _CJK_RUN.findall(text.lower()):
        if run.isascii() or len(run) == 1:
            out.add(run)
        else:
            out.update(run[i : i + 2] for i in range(len(run) - 1))
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def numbers(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for value, unit in _NUMBER_UNIT.findall(text):
        out.setdefault(unit, set()).add(value)
    return out


def _topic(p: KBPassage) -> set[str]:
    return {t for t in bigrams(p.title + p.text) if t not in STOP}


# ---------------------------------------------------------------- checks


def structural_errors(passages: Sequence[KBPassage], *, min_len: int = 10, max_len: int = 400) -> list[Issue]:
    issues: list[Issue] = []
    ids = [p.id for p in passages]
    for pid in sorted({i for i in ids if ids.count(i) > 1}):
        issues.append(Issue("error", "duplicate_id", [pid], f"编号 {pid} 出现了 {ids.count(pid)} 次"))
    known = set(ids)
    for p in passages:
        if not p.title.strip():
            issues.append(Issue("error", "missing_title", [p.id], "缺少标题：检索与引用都依赖标题"))
        if not p.text.strip():
            issues.append(Issue("error", "empty_text", [p.id], "正文为空"))
        elif not min_len <= len(p.text) <= max_len:
            issues.append(Issue("error", "length_outlier", [p.id], f"正文长度 {len(p.text)}，不在 {min_len}–{max_len} 之间"))
        for ref in sorted(set(_REFERENCE.findall(p.text)) - known - {p.id}):
            issues.append(Issue("error", "dangling_reference", [p.id], f"引用了不存在的条款 {ref}", {"reference": ref}))
    return issues


def redundancy(passages: Sequence[KBPassage], *, threshold: float = 0.6) -> list[Issue]:
    issues = []
    grams = [bigrams(p.text) for p in passages]
    for i in range(len(passages)):
        for j in range(i + 1, len(passages)):
            a, b = passages[i], passages[j]
            sim = jaccard(grams[i], grams[j])
            contained = a.text.strip() in b.text or b.text.strip() in a.text
            if sim >= threshold or contained:
                issues.append(
                    Issue(
                        "redundancy",
                        "near_duplicate",
                        [a.id, b.id],
                        f"正文相似度 {sim:.2f}{'，且一条包含另一条' if contained else ''}",
                        {"similarity": round(sim, 3)},
                    )
                )
    return issues


def neighbours(passages: Sequence[KBPassage], *, k: int = 3) -> set[tuple[str, str]]:
    """Pairs that a retriever would bring back together: each passage's top-k BM25 neighbours.

    This is ConsentTrace's own small BM25 over the base under check (it must also work on a
    base with planted or poisoned passages that the agent's retriever has never seen).
    """
    docs = [list(bigrams(p.title + p.text) - STOP) for p in passages]
    n = len(docs)
    avg = sum(len(d) for d in docs) / n if n else 0.0
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(q: list[str], d: list[str]) -> float:
        terms = set(d)
        norm = 1.5 * (0.25 + 0.75 * len(d) / avg) if avg else 1.0
        return sum(idf[t] * 2.5 / (1 + norm) for t in set(q) if t in terms)

    pairs: set[tuple[str, str]] = set()
    for i, q in enumerate(docs):
        ranked = sorted(((score(q, d), j) for j, d in enumerate(docs) if j != i), reverse=True)
        for s_, j in ranked[:k]:
            if s_ > 0:
                a, b = sorted((passages[i].id, passages[j].id))
                pairs.add((a, b))
    return pairs


def _scopes(text: str, cues: Sequence[str], width: int) -> list[set[str]]:
    out = []
    for cue in cues:
        start = text.find(cue)
        while start != -1:
            out.append(bigrams(text[start + len(cue) : start + len(cue) + width]) - STOP)
            start = text.find(cue, start + len(cue))
    return out


def obligation_conflict(a: KBPassage, b: KBPassage) -> set[str]:
    """Words of a requirement in one passage that the other passage waives (empty: no conflict)."""
    shared: set[str] = set()
    for must_p, free_p in ((a, b), (b, a)):
        for waived in _scopes(free_p.text, NEED_NOT, WAIVE_SCOPE):
            for required in _scopes(must_p.text, MUST, MUST_SCOPE):
                shared |= waived & required
    return shared


def conflict_candidates(passages: Sequence[KBPassage], *, k: int = 3) -> list[Issue]:
    """Within retrieval neighbourhoods: different numbers for the same unit, or a requirement one passage waives."""
    issues = []
    by_id = {p.id: p for p in passages}
    for a_id, b_id in sorted(neighbours(passages, k=k)):
        a, b = by_id[a_id], by_id[b_id]
        na, nb = numbers(a.text), numbers(b.text)
        for unit in sorted(set(na) & set(nb)):
            if na[unit] != nb[unit]:
                issues.append(
                    Issue(
                        "conflict",
                        "numeric_conflict",
                        [a.id, b.id],
                        f"检索邻域内「{unit}」的取值不同：{'/'.join(sorted(na[unit]))} 与 {'/'.join(sorted(nb[unit]))}",
                        {"unit": unit, "a": sorted(na[unit]), "b": sorted(nb[unit])},
                    )
                )
        if shared := obligation_conflict(a, b):
            issues.append(
                Issue(
                    "conflict",
                    "obligation_conflict",
                    [a.id, b.id],
                    f"一条要求、另一条豁免同一件事（共同词：{'、'.join(sorted(shared))}）",
                    {"shared": sorted(shared)},
                )
            )
    return issues


def retrieval_quality(queries: Sequence[dict[str, Any]], search: Search, *, k: int = 3) -> dict[str, Any]:
    """Recall@1, Recall@k and MRR of the agent's own retriever on queries with a gold passage."""
    rows = []
    for q in queries:
        ranked = search(q["query"], max(k, 10))
        rank = ranked.index(q["gold"]) + 1 if q["gold"] in ranked else None
        rows.append({**q, "rank": rank, "top": ranked[:k]})
    n = len(rows)

    def share(pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        num = sum(1 for r in rows if pred(r))
        return {"num": num, "den": n, "rate": num / n if n else None}

    misses = [r for r in rows if r["rank"] is None or r["rank"] > k]
    confusions: dict[str, int] = {}
    for r in rows:
        if r["rank"] != 1 and r["top"]:
            key = f"{r['gold']}→{r['top'][0]}"
            confusions[key] = confusions.get(key, 0) + 1
    return {
        "k": k,
        "queries": n,
        "recall_at_1": share(lambda r: r["rank"] == 1),
        f"recall_at_{k}": share(lambda r: r["rank"] is not None and r["rank"] <= k),
        "mrr": round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 4) if n else None,
        "misses": misses,
        "confusions": dict(sorted(confusions.items(), key=lambda kv: -kv[1])),
        "rows": rows,
    }


def check_kb(
    passages: Sequence[KBPassage], *, queries: Sequence[dict[str, Any]] = (), search: Search | None = None, k: int = 3
) -> dict[str, Any]:
    issues = [*structural_errors(passages), *redundancy(passages), *conflict_candidates(passages)]
    counts = {kind: sum(1 for i in issues if i.kind == kind) for kind in ("error", "redundancy", "conflict")}
    return {
        "passages": len(passages),
        "issues": [asdict(i) for i in issues],
        "counts": counts,
        "retrieval": retrieval_quality(queries, search, k=k) if queries and search else None,
    }


# ---------------------------------------------------------------- self-test with seeded faults


def _bump(match: re.Match[str]) -> str:
    value = match.group(1)
    new = str(int(float(value)) * 2 + 1) if "." not in value else str(float(value) * 2)
    return f"{new}{match.group(2)}"


def seed_faults(passages: Sequence[KBPassage], *, seed: int = 0) -> tuple[list[KBPassage], list[dict[str, Any]]]:
    """A copy of the base with one fault of each kind planted, and the ground truth for each."""
    rng = random.Random(seed)
    base = list(passages)
    with_numbers = [p for p in base if _NUMBER_UNIT.search(p.text)]
    planted: list[dict[str, Any]] = []
    out = list(base)

    dup = rng.choice(base)
    out.append(KBPassage(f"{dup.id}-DUP", dup.title + "（重述）", dup.text.replace("，", "；", 1) + "特此重申。"))
    planted.append({"kind": "redundancy", "rule": "near_duplicate", "passages": [dup.id, f"{dup.id}-DUP"]})

    if with_numbers:
        src = rng.choice(with_numbers)
        changed = _NUMBER_UNIT.sub(_bump, src.text, count=1)
        out.append(KBPassage(f"{src.id}-ALT", src.title + "（补充说明）", changed))
        planted.append({"kind": "conflict", "rule": "numeric_conflict", "passages": [src.id, f"{src.id}-ALT"]})

    victim_idx = rng.randrange(len(out))
    victim = out[victim_idx]
    out[victim_idx] = KBPassage(victim.id, victim.title, victim.text + "具体流程详见 POL-99。")
    planted.append({"kind": "error", "rule": "dangling_reference", "passages": [victim.id]})

    untitled_idx = rng.choice([i for i in range(len(out)) if i != victim_idx])
    untitled = out[untitled_idx]
    out[untitled_idx] = KBPassage(untitled.id, "", untitled.text)
    planted.append({"kind": "error", "rule": "missing_title", "passages": [untitled.id]})
    return out, planted


def score_planted(report: dict[str, Any], planted: Sequence[dict[str, Any]]) -> dict[str, Any]:
    found = []
    for fault in planted:
        hit = any(i["rule"] == fault["rule"] and set(fault["passages"]) <= set(i["passages"]) for i in report["issues"])
        found.append({**fault, "detected": hit})
    return {"planted": len(planted), "detected": sum(f["detected"] for f in found), "faults": found}


def poison_conflicts(passages: Sequence[KBPassage], poisons: Sequence[KBPassage]) -> list[dict[str, Any]]:
    """For each poisoned passage (e.g. from the attack library), which real clauses it is flagged against."""
    out = []
    for poison in poisons:
        issues = [i for i in conflict_candidates([*passages, poison]) if poison.id in i.passages]
        out.append(
            {
                "id": poison.id,
                "title": poison.title,
                "text": poison.text,
                "flagged": bool(issues),
                "against": sorted({pid for i in issues for pid in i.passages if pid != poison.id}),
                "rules": sorted({i.rule for i in issues}),
            }
        )
    return out
