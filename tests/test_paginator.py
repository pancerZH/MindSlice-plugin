"""Paginator properties (PLAN 4.3 / 8): every page within the limit, lossless, never half a card."""

from __future__ import annotations

import random
import re
import unittest

import helpers  # noqa: F401  (paths)
import core
from core import SEP, Block, deliver, reassemble, utf16_len

LIMIT = 9500
SNAP = "0123abcd"


def card(i: int, body: str) -> Block:
    addr = f"@overlay/cards/c{i}"
    return Block(f"## Card {i} ({addr})\n\nSummary {i}.\n\n{body}", addr, {"address": addr, "title": f"Card {i}"})


def fixed() -> list[Block]:
    return [Block("# preamble\n\nWorkspace: /x", "preamble"), Block("instructions " * 300, "instructions")]


class PaginatorTest(unittest.TestCase):
    def check_complete(self, blocks: list[Block], max_pages: int = 50) -> list[str]:
        pages = deliver(blocks, LIMIT, max_pages, SNAP)
        for p in pages:
            self.assertLessEqual(utf16_len(p), LIMIT)
            self.assertNotIn("could not be delivered safely", p)
        self.assertEqual(reassemble(pages), SEP.join(b.text for b in blocks))
        self.assertTrue(pages[-1].endswith(f"[MindSlice standing memory complete · {len(pages)} pages · "
                                           f"{sum(1 for b in blocks if b.card)} cards]"))
        for i, p in enumerate(pages, 1):
            self.assertTrue(p.startswith(f"[MindSlice standing memory · page {i}/{len(pages)} · snapshot {SNAP}]"))
        return pages

    def test_zero_cards(self) -> None:
        pages = self.check_complete(fixed())
        self.assertEqual(len(pages), 1)

    def test_many_small_cards(self) -> None:
        blocks = fixed() + [card(i, "- fact " * random.Random(i).randint(5, 400)) for i in range(60)]
        pages = self.check_complete(blocks)
        self.assertGreater(len(pages), 2)
        self.assertFalse(any("（续" in p for p in pages))  # nothing needed splitting

    def test_large_chinese_card(self) -> None:
        body = "\n\n".join("这是一段很长的中文规则说明，用于测试分页器在中文环境下的表现。" * 20 for _ in range(30))
        pages = self.check_complete(fixed() + [card(1, body), card(2, "- 短卡片")])
        self.assertTrue(any("（续 2/" in p for p in pages))

    def test_zwj_emoji_without_breaks(self) -> None:
        family = "👨‍👩‍👧‍👦"
        body = (family + "👍🏽" + "é") * 2500  # no newline anywhere: forces character cuts
        blocks = fixed() + [card(1, body)]
        pages = self.check_complete(blocks)
        # no cut next to a joiner, skin tone or combining mark
        pieces = [re.sub(r"^\[.*?\]\n\n", "", p) for p in pages]
        for p in pieces:
            m = re.search(r"（续 \d+/\d+：[^\n]*）\n", p)
            if not m:
                continue
            start = p[m.end():m.end() + 1]
            self.assertFalse(core._joins(start), repr(start))

    def test_code_fence_card(self) -> None:
        code = "```python\n" + "\n".join(f"x_{i} = {i}  # line" for i in range(1200)) + "\n```\n"
        body = ("Intro paragraph.\n\n" + code + "\nAfter the code.\n\n") * 2  # ~ 30,000+ characters
        self.assertGreater(len(body), 30000)
        pages = self.check_complete(fixed() + [card(1, body)])
        self.assertGreater(len(pages), 3)

    def test_exactly_at_the_limit(self) -> None:
        budget = core.body_budget(LIMIT)
        blocks = [Block("a" * budget, "one")]
        pages = self.check_complete(blocks)
        self.assertEqual(len(pages), 1)
        self.assertEqual(utf16_len(pages[0]) <= LIMIT, True)
        blocks = [Block("a" * (budget + 1), "one")]
        self.assertEqual(len(self.check_complete(blocks)), 2)
        # two blocks that fit exactly with the separator
        half = (budget - len(SEP)) // 2
        self.assertEqual(len(self.check_complete([Block("b" * half, "x"), Block("c" * half, "y")])), 1)

    def test_astral_characters_count_double(self) -> None:
        budget = core.body_budget(LIMIT)
        blocks = [Block("😀" * (budget // 2 + 1), "astral")]  # fits by characters, not by UTF-16 units
        self.assertEqual(len(self.check_complete(blocks)), 2)

    def test_overflow_never_half_a_card(self) -> None:
        blocks = fixed() + [card(i, "- 规则 " * 1500) for i in range(30)]
        pages = deliver(blocks, LIMIT, 4, SNAP)
        self.assertEqual(len(pages), 4)
        for p in pages:
            self.assertLessEqual(utf16_len(p), LIMIT)
        self.assertIn("# Standing memory overflow", pages[-1])
        self.assertIn("INCOMPLETE", pages[-1])
        self.assertNotIn("complete ·", pages[-1])
        delivered = SEP.join(pages[:-1])
        cards = [b for b in blocks if b.card]
        for b in cards:
            whole = b.text in delivered
            listed = f"- {b.card['address']} — " in pages[-1]
            self.assertTrue(whole != listed, b.card["address"])  # each card exactly one way
        # no continuation marker without all its pieces
        for m in re.finditer(r"（续 (\d+)/(\d+)：([^\n]*) · ", delivered):
            label = m.group(3)
            self.assertIn(f"（续 {m.group(2)}/{m.group(2)}：{label} · ", delivered)

    def test_overflow_list_is_bounded(self) -> None:
        blocks = fixed() + [card(i, "x" * 9000) for i in range(3000)]
        pages = deliver(blocks, LIMIT, 4, SNAP)
        self.assertEqual(len(pages), 4)
        self.assertLessEqual(utf16_len(pages[-1]), LIMIT)
        self.assertIn("more: call manifest(include_always=true)", pages[-1])

    def test_split_text_is_lossless(self) -> None:
        rng = random.Random(7)
        alphabet = "ab \n\n中文😀‍```~"
        for _ in range(200):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 3000)))
            budget = rng.randint(50, 600)
            pieces = core.split_text(text, budget)
            self.assertEqual("".join(pieces), text)
            for piece in pieces:
                self.assertLessEqual(utf16_len(piece), budget)
                self.assertTrue(piece)


if __name__ == "__main__":
    unittest.main()
