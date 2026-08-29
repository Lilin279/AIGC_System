from __future__ import annotations

import re


def search_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = value.casefold().strip()
        if len(normalized) >= 2 and normalized not in seen:
            seen.add(normalized)
            tokens.append(normalized)

    for word in re.findall(r"[A-Za-z0-9_]{2,}", text):
        add(word)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(sequence) <= 8:
            add(sequence)
        for width in (2, 3):
            for index in range(max(0, len(sequence) - width + 1)):
                add(sequence[index:index + width])
    return tokens[:80]


def index_text(text: str) -> str:
    return " ".join(search_tokens(text))


def fts_query(text: str) -> str:
    tokens = search_tokens(text)
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:24])
