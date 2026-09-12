"""Regression tests for layout-aware statute extraction.

User journey: as an evidence reader, I need each article heading to precede the
article body in extraction order so that an article-level source span contains
the correct text instead of a page navigation list.

Run from the repository root with the preprocessing environment:
    .venv_pre/bin/python -m tests.preprocess.test_statute_layout
"""
from __future__ import annotations

import os

from scripts.preprocess.extract import extract_pages, flat_lines


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

LAW_CASES = (
    ("訴願法.pdf 的副本.pdf", "人民對於中央或地方機關之行政處分"),
    ("行政程序法.pdf 的副本.pdf", "為使行政行為遵循公正、公開與民主之程序"),
    ("洗錢防制法.pdf 的副本.pdf", "為防制洗錢，打擊犯罪"),
    (
        "行政院及各級行政機關訴願審議委員會審議規則.pdf 的副本.pdf",
        "本規則依訴願法",
    ),
)


def _assert_first_article_is_contiguous(filename: str, body_prefix: str) -> None:
    path = os.path.join(REPO_ROOT, "data", "raw", "相關法規", filename)
    pages = extract_pages(path, reading_order="visual")
    lines = [line["text"] for line in flat_lines(pages)]

    first = lines.index("第 1 條")
    second = lines.index("第 2 條")
    article_body = "".join(lines[first + 1:second])

    assert second > first + 1, filename
    assert body_prefix in article_body, filename


def main() -> None:
    for filename, body_prefix in LAW_CASES:
        _assert_first_article_is_contiguous(filename, body_prefix)
        print(f"  [PASS] {filename} article 1 reading order")


if __name__ == "__main__":
    main()
