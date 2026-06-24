"""文本切分（父子索引的子颗粒度）。

中文按自然段/句子贪心打包成 ~size 字的 chunk，带 overlap；单文档限 max_chunks。
短文档（curated/juhe）→ 1 个 chunk；长文档（新闻联播）→ 多 chunk 覆盖正文。
"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])")


def _paragraphs(text: str) -> list[str]:
    parts: list[str] = []
    for line in (text or "").replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line) <= 1000:
            parts.append(line)
        else:  # 超长段再按句子切
            parts.extend(s.strip() for s in _SENT_SPLIT.split(line) if s.strip())
    return parts


def chunk_text(text: str, size: int = 600, overlap: int = 120, max_chunks: int = 8) -> list[str]:
    """贪心打包：把段落拼到接近 size 就成一个 chunk，相邻 chunk 保留 overlap 字重叠。"""
    paras = _paragraphs(text)
    if not paras:
        return []
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if buf and len(buf) + len(para) + 1 > size:
            chunks.append(buf)
            if len(chunks) >= max_chunks:
                return chunks
            buf = (buf[-overlap:] + "\n" + para) if overlap else para  # 带重叠
        else:
            buf = (buf + "\n" + para) if buf else para
    if buf and len(chunks) < max_chunks:
        chunks.append(buf)
    return chunks
