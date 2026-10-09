"""商品知识库检索：把较长的知识库切成段落，按与买家问题的相关度挑选，控制提示词长度。

不依赖向量模型：中文按字的二元组、英文数字按单词，用 BM25 打分。知识库通常只有几十段，足够准确且零成本。
"""

import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.IGNORECASE)
_CJK = re.compile(r"[一-鿿]")
_STOP = set("的了吗呢啊吧是我你他她它们这那有在和与就都也还要会能可以么什么怎么多少")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = _WORD.findall(text)
    chars = [c for c in text if _CJK.match(c)]
    tokens += [a + b for a, b in zip(chars, chars[1:], strict=False)]
    tokens += [c for c in chars if c not in _STOP]
    return tokens


def split_chunks(knowledge: str, max_chunk: int = 300) -> list[str]:
    """按空行 / 标题 / 问答条目切分，过长的段落再按句子切开。"""
    blocks: list[str] = []
    current: list[str] = []
    for line in knowledge.splitlines():
        stripped = line.strip()
        starts_new = not stripped or re.match(r"^(#+\s|Q[:：]|问[:：]|\d+[.、)]|[-*•]\s)", stripped)
        if starts_new and current:
            blocks.append("\n".join(current))
            current = []
        if stripped:
            current.append(stripped)
    if current:
        blocks.append("\n".join(current))
    chunks: list[str] = []
    for block in blocks:
        while len(block) > max_chunk:
            cut = max(block.rfind(p, 0, max_chunk) for p in "。！？；\n")
            cut = cut + 1 if cut > max_chunk // 3 else max_chunk
            chunks.append(block[:cut].strip())
            block = block[cut:].strip()
        if block:
            chunks.append(block)
    return chunks


def rank_chunks(chunks: list[str], query: str, k1: float = 1.2, b: float = 0.75) -> list[float]:
    docs = [Counter(tokenize(c)) for c in chunks]
    if not docs:
        return []
    avgdl = sum(sum(d.values()) for d in docs) / len(docs) or 1
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.keys())
    q_terms = set(tokenize(query))
    scores = []
    for d in docs:
        dl = sum(d.values()) or 1
        s = 0.0
        for t in q_terms:
            tf = d.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    return scores


def select_knowledge(knowledge: str, query: str, max_chars: int = 1500) -> str:
    """返回与问题最相关的若干段（保持原文顺序）。知识库本身不长时原样返回。"""
    knowledge = (knowledge or "").strip()
    if len(knowledge) <= max_chars:
        return knowledge
    chunks = split_chunks(knowledge)
    scores = rank_chunks(chunks, query)
    order = sorted(range(len(chunks)), key=lambda i: (-scores[i], i))
    picked: set[int] = set()
    used = 0
    for i in order:
        if scores[i] <= 0 and picked:
            break
        if used + len(chunks[i]) > max_chars:
            continue
        picked.add(i)
        used += len(chunks[i]) + 1
    if not picked:  # 都不相关：给出开头的通用信息
        for i, c in enumerate(chunks):
            if used + len(c) > max_chars:
                break
            picked.add(i)
            used += len(c) + 1
    return "\n".join(chunks[i] for i in sorted(picked))
