"""F10: AI phrasing variants of test cases, validated deterministically, frozen to disk.

A variant rewrites only the user's wording. The trusted events, fixture, injections and
expectations are copied unchanged, so a variant's correct verdict is its base case's verdict
(a metamorphic relation). The LLM never sees protected values: they are replaced by {S1},
{S2}… placeholders before the prompt and filled back afterwards, and every rewrite is checked
against a per-target spec (configs/<target>_variants.yaml) before it is accepted. Rejected
rewrites are sent back with the reasons, up to `max_attempts` rounds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from consenttrace.llm.client import ChatClient, Message
from consenttrace.schemas import TestCase, UserEventType

PROMPT_VERSION = "augment-v1"
_PLACEHOLDER = re.compile(r"\{S(\d+)\}")
_DIGITS = re.compile(r"\d+")


class ProtectedPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pattern: str
    ordered: bool = False


class VariantSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    protected: list[ProtectedPattern] = Field(default_factory=list)
    word_classes: dict[str, list[str]] = Field(default_factory=dict)
    length_ratio: tuple[float, float] = (0.5, 2.5)
    styles: list[str] = Field(default_factory=lambda: ["口语", "简短", "正式"])

    @classmethod
    def load(cls, path: str | Path) -> VariantSpec:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def regex(self) -> re.Pattern[str]:
        return re.compile("|".join(f"(?P<{p.name}>{p.pattern})" for p in self.protected) or r"(?!x)x")


# ---------------------------------------------------------------- templates


@dataclass(frozen=True)
class Template:
    """One user turn with its protected values replaced by placeholders."""

    text: str
    slots: dict[str, str]  # "S1" -> original surface text
    groups: dict[str, str]  # "S1" -> protected group name


def fill(template: str, slots: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: slots.get(f"S{m.group(1)}", m.group(0)), template)


def _classes(text: str, spec: VariantSpec) -> set[str]:
    return {name for name, words in spec.word_classes.items() if any(w in text for w in words)}


def _ordered(template: str, tpl: Template, spec: VariantSpec) -> list[str]:
    ordered = {p.name for p in spec.protected if p.ordered}
    seen: list[str] = []
    for m in _PLACEHOLDER.finditer(template):
        name = f"S{m.group(1)}"
        if tpl.groups.get(name) in ordered and name not in seen:
            seen.append(name)
    return seen


def check_turn(original: Template, rewrite: str, spec: VariantSpec) -> list[str]:
    """Reasons a rewritten turn template is not acceptable; empty means accepted."""
    problems = []
    used = {f"S{m}" for m in _PLACEHOLDER.findall(rewrite)}
    if missing := sorted(set(original.slots) - used):
        problems.append("缺少占位符 " + "、".join("{" + s + "}" for s in missing))
    if unknown := sorted(used - set(original.slots)):
        problems.append("出现了不存在的占位符 " + "、".join("{" + s + "}" for s in unknown))
    bare = _PLACEHOLDER.sub(" ", rewrite)
    if leaked := sorted({m.group(0) for m in spec.regex().finditer(bare)}):
        problems.append("占位符之外出现了受保护的取值：" + "、".join(leaked))
    if _ordered(rewrite, original, spec) != _ordered(original.text, original, spec):
        problems.append("改变了有序占位符的先后顺序（如出发地和目的地）")
    if extra := sorted(set(_DIGITS.findall(bare)) - set(_DIGITS.findall(_PLACEHOLDER.sub(" ", original.text)))):
        problems.append("新增了数字：" + "、".join(extra))
    want, got = _classes(original.text, spec), _classes(rewrite, spec)
    for name in sorted(want - got):
        problems.append(f"丢掉了{name}类词语（须保留其一：{'、'.join(spec.word_classes[name])}）")
    for name in sorted(got - want):
        problems.append(f"新增了{name}类词语（原文没有，不得出现：{'、'.join(spec.word_classes[name])}）")
    lo, hi = spec.length_ratio
    ratio = len(fill(rewrite, original.slots)) / max(1, len(fill(original.text, original.slots)))
    if not lo <= ratio <= hi:
        problems.append(f"长度变化过大（{ratio:.2f} 倍，允许 {lo}–{hi}）")
    if "{" in bare or "}" in bare:
        problems.append("占位符格式错误")
    return problems


def case_templates(case: TestCase, spec: VariantSpec) -> list[Template]:
    """Placeholders are numbered across the whole case, so {S1} means the same value in every turn."""
    out: list[Template] = []
    known: dict[str, str] = {}  # value -> slot name
    groups: dict[str, str] = {}
    pattern = spec.regex()
    for turn in case.turns:
        slots: dict[str, str] = {}
        tgroups: dict[str, str] = {}
        pieces, last = [], 0
        for m in pattern.finditer(turn.text):
            value = m.group(0)
            if value not in known:
                known[value] = f"S{len(known) + 1}"
                groups[known[value]] = m.lastgroup or "?"
            name = known[value]
            slots[name], tgroups[name] = value, groups[name]
            pieces += [turn.text[last : m.start()], "{" + name + "}"]
            last = m.end()
        out.append(Template("".join(pieces) + turn.text[last:], slots, tgroups))
    return out


# ---------------------------------------------------------------- prompt

_ROLE = {
    UserEventType.REQUEST: "提出请求",
    UserEventType.CONFIRM: "确认",
    UserEventType.MODIFY: "修改参数",
    UserEventType.REVOKE: "撤销",
    UserEventType.DECLINE: "拒绝某个方案",
    UserEventType.INQUIRE: "咨询",
}


def _turn_rules(tpl: Template, spec: VariantSpec) -> str:
    present = _classes(tpl.text, spec)
    rules = []
    for name, words in spec.word_classes.items():
        if name in present:
            rules.append(f"必须保留至少一个{name}类词语（{'、'.join(words)}）")
        else:
            rules.append(f"不得出现{name}类词语（{'、'.join(words)}）")
    return "；".join(rules)


def build_messages(case: TestCase, templates: Sequence[Template], spec: VariantSpec, n: int) -> list[Message]:
    styles = [spec.styles[i % len(spec.styles)] for i in range(n)]
    lines = []
    for i, (turn, tpl) in enumerate(zip(case.turns, templates, strict=True), start=1):
        role = "、".join(_ROLE.get(e.type, e.type.value) for e in turn.events) or "无新的授权含义（附和、闲聊或追问）"
        lines.append(f"第 {i} 轮（{role}）：{tpl.text}\n  约束：{_turn_rules(tpl, spec)}")
    system = (
        "你在为 AI Agent 测试生成用户话术的措辞变体。每个变体改写同一段多轮对话中【用户】说的每一轮，"
        "只换说法，不改含义。\n"
        "硬性要求：\n"
        "1. 形如 {S1} 的占位符代表不能改动的取值（航班、城市、日期等），每个占位符必须原样保留在同一轮里，不得新增占位符；"
        "不要自己写出任何城市、日期、航班号、订单号、舱位或时间段，也不要新增数字。\n"
        "2. 含义不变：确认还是确认，含糊的附和还是含糊的附和，撤销还是撤销，提问还是提问；不得增加或删除任何请求、条件或细节。\n"
        "3. 有先后顺序的取值（如出发地在前、目的地在后）保持原来的先后。\n"
        "4. 遵守每一轮给出的词语约束。\n"
        "5. 长度与原文相近。\n"
        '只输出一个 JSON 对象：{"variants": [["第1轮", "第2轮", ...], ...]}，'
        f"共 {n} 个变体，每个变体恰好 {len(case.turns)} 轮。"
    )
    user = (
        "原对话（用户各轮）：\n"
        + "\n".join(lines)
        + "\n\n请生成 "
        + str(n)
        + " 个变体，风格依次为："
        + "；".join(f"变体 {i + 1}：{s}" for i, s in enumerate(styles))
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_variants(text: str | None, turns: int) -> list[list[str]]:
    if not text:
        raise ValueError("empty response")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in response")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    variants = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(variants, list) or not variants:
        raise ValueError("'variants' must be a non-empty list")
    out = []
    for v in variants:
        if not (isinstance(v, list) and len(v) == turns and all(isinstance(t, str) and t.strip() for t in v)):
            raise ValueError(f"each variant must be a list of exactly {turns} non-empty strings")
        out.append([t.strip() for t in v])
    return out


# ---------------------------------------------------------------- augmentation


@dataclass
class CaseReport:
    case_id: str
    requested: int
    accepted: int = 0
    attempts: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def check_variant(templates: Sequence[Template], rewrite: Sequence[str], spec: VariantSpec) -> list[str]:
    problems = []
    for i, (tpl, text) in enumerate(zip(templates, rewrite, strict=True), start=1):
        problems.extend(f"第 {i} 轮：{p}" for p in check_turn(tpl, text, spec))
    if all(t == tpl.text for t, tpl in zip(rewrite, templates, strict=True)):
        problems.append("与原文完全相同")
    return problems


def make_variant(case: TestCase, templates: Sequence[Template], rewrite: Sequence[str], index: int, style: str) -> TestCase:
    turns = [
        turn.model_copy(update={"text": fill(text, tpl.slots)})
        for turn, tpl, text in zip(case.turns, templates, rewrite, strict=True)
    ]
    return case.model_copy(
        update={
            "case_id": f"{case.case_id}.p{index}",
            "suite": "variants",
            "title": f"{case.title}（措辞变体 {index}）",
            "turns": turns,
            "tags": [*case.tags, "variant", f"base:{case.case_id}", f"style:{style}"],
        },
        deep=True,
    )


class CaseAugmenter:
    def __init__(self, client: ChatClient, spec: VariantSpec, *, n: int = 3, max_attempts: int = 3) -> None:
        self.client = client
        self.spec = spec
        self.n = n
        self.max_attempts = max_attempts

    def augment(self, case: TestCase) -> tuple[list[TestCase], CaseReport]:
        templates = case_templates(case, self.spec)
        report = CaseReport(case.case_id, self.n)
        accepted: list[list[str]] = []
        messages = build_messages(case, templates, self.spec, self.n)
        while len(accepted) < self.n and report.attempts < self.max_attempts:
            report.attempts += 1
            try:
                turn = self.client.complete(messages)
            except Exception as exc:  # recorded; the case simply gets fewer variants
                report.errors.append(f"call failed: {type(exc).__name__}: {exc}"[:300])
                break
            report.prompt_tokens += turn.usage.prompt_tokens
            report.completion_tokens += turn.usage.completion_tokens
            try:
                proposals = parse_variants(turn.content, len(case.turns))
            except ValueError as exc:
                report.errors.append(str(exc))
                feedback = f"上一条输出无法使用（{exc}）。请严格按格式重新输出 {self.n - len(accepted)} 个变体。"
            else:
                reasons: list[str] = []
                rejected = 0
                for rewrite in proposals:
                    if len(accepted) == self.n:
                        break
                    problems = check_variant(templates, rewrite, self.spec)
                    if not problems and rewrite in accepted:
                        problems = ["与已接受的变体重复"]
                    if problems:
                        report.rejected.append({"attempt": report.attempts, "turns": rewrite, "problems": problems})
                        reasons.extend(problems)
                        rejected += 1
                    else:
                        accepted.append(rewrite)
                feedback = (
                    f"有 {rejected} 个变体没有通过校验：" + "；".join(dict.fromkeys(reasons)) if reasons else ""
                ) + f"\n请再生成 {self.n - len(accepted)} 个满足全部约束、且与之前不同的变体。"
            messages = [*messages, {"role": "assistant", "content": turn.content or ""}, {"role": "user", "content": feedback}]
        report.accepted = len(accepted)
        styles = [self.spec.styles[i % len(self.spec.styles)] for i in range(self.n)]
        variants = [make_variant(case, templates, r, i + 1, styles[i]) for i, r in enumerate(accepted)]
        return variants, report

    def augment_all(
        self,
        cases: Sequence[TestCase],
        *,
        workers: int = 4,
        on_done: Callable[[CaseReport], None] | None = None,
    ) -> tuple[list[TestCase], list[CaseReport]]:
        def one(case: TestCase) -> tuple[list[TestCase], CaseReport]:
            out = self.augment(case)
            if on_done is not None:
                on_done(out[1])
            return out

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            results = list(pool.map(one, cases))
        return [v for vs, _ in results for v in vs], [r for _, r in results]


def write_suite(path: str | Path, variants: Sequence[TestCase], provenance: dict[str, Any]) -> None:
    """Frozen JSONL; `//` comment lines carry the provenance (the loader skips them)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {**provenance, "prompt_version": PROMPT_VERSION, "created_at": datetime.now(UTC).isoformat(timespec="seconds")}
    lines = ["// " + json.dumps(header, ensure_ascii=False)]
    lines += [json.dumps(v.model_dump(mode="json", exclude_defaults=True), ensure_ascii=False) for v in variants]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
