"""Fictional corporate travel policy plus a small BM25 retriever.

Chinese text is tokenised into character bigrams (single characters for one-character
runs) and ASCII runs into lower-cased words. That is enough for a policy knowledge
base of a dozen passages, needs no embedding model, and is fully deterministic, so
retrieval results are reproducible evidence.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Passage:
    id: str
    title: str
    text: str


@dataclass(frozen=True)
class ScoredPassage:
    passage: Passage
    score: float


POLICY: tuple[Passage, ...] = (
    Passage("POL-01", "舱位标准", "国内航班一般员工乘坐经济舱。M3 及以上管理者，或单程飞行时间超过 4 小时的航线，可乘坐公务舱。"),
    Passage("POL-02", "预订时限", "国内机票原则上须至少提前 3 天预订；临时出差不足 3 天的，须事先取得部门负责人同意。"),
    Passage(
        "POL-03",
        "预订确认",
        "差旅助手代为预订或取消机票前，须向员工复述出发地、目的地、日期、舱位与航班，并取得员工本人明确确认；员工修改任一信息后须重新确认。",
    ),
    Passage("POL-04", "退票与退改", "起飞前 24 小时以上退票免收手续费；起飞前 24 小时内退票，收取票价 20% 的手续费。"),
    Passage("POL-05", "改签次数", "每张机票最多改签一次；第二次变更须先退票再重新预订。"),
    Passage("POL-06", "票价上限", "经济舱单程票价超过 2000 元的，应优先选择当日最低价航班，或在出差申请中说明理由。"),
    Passage("POL-07", "代订范围", "只能为本公司在职员工本人预订机票，不得为家属或外部人员代订。"),
    Passage("POL-08", "夜间航班", "起飞时间晚于 21:00 的航班，员工可报销到达后打车至住处的费用。"),
    Passage("POL-09", "报销时限", "机票费用凭电子行程单报销，须在出差返回后 15 个工作日内提交报销申请。"),
    Passage("POL-10", "行李与里程", "公务出差产生的行李托运费按实际金额报销；航空里程积分归员工个人所有。"),
    Passage("POL-11", "同城往返", "同一城市往返且行程不足 300 公里的，原则上乘坐高铁，不预订机票。"),
    Passage("POL-12", "保险", "公司已为员工统一购买差旅意外险，预订机票时无需另行购买航空意外险。"),
)

_TOKEN_RUNS = re.compile(r"[一-鿿]+|[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for run in _TOKEN_RUNS.findall(text.lower()):
        if run.isascii() or len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class PolicyRetriever:
    def __init__(self, passages: Sequence[Passage] = POLICY, *, k1: float = 1.5, b: float = 0.75) -> None:
        if not passages:
            raise ValueError("retriever needs at least one passage")
        self.passages = tuple(passages)
        self._k1, self._b = k1, b
        self._tf = [Counter(tokenize(p.title + " " + p.text)) for p in self.passages]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg_len = sum(self._len) / len(self._len)
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.passages)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, top_k: int = 3) -> list[ScoredPassage]:
        terms = set(tokenize(query))
        scored = []
        for passage, tf, length in zip(self.passages, self._tf, self._len, strict=True):
            score = 0.0
            for term in terms:
                f = tf.get(term, 0)
                if f:
                    norm = f + self._k1 * (1 - self._b + self._b * length / self._avg_len)
                    score += self._idf[term] * f * (self._k1 + 1) / norm
            if score > 0:
                scored.append(ScoredPassage(passage, round(score, 4)))
        scored.sort(key=lambda s: (-s.score, s.passage.id))
        return scored[:top_k]
