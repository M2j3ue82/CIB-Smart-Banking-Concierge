"""Unit tests for scripts/preprocess_cib_data.py  (run: python -m unittest discover -s tests -v)"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preprocess_cib_data as pp  # noqa: E402

TODAY = date(2026, 11, 18)

GOOD = """# Title
> preamble line

## بطاقة تجريبية

```yaml
product_id: test-card
product_name_en: Test Card
category: credit_cards
language: ar
source: https://www.cibeg.com/en/personal/test
last_verified: 2026-11-13
```

- نقطة أولى
- نقطة ثانية

## معلومات غير متوفرة في هذه النسخة

- الرسوم.
"""


def run(text, **kw):
    return pp.process_text(text, max_chars=kw.pop("max_chars", 1000), max_age_days=90, strict=kw.pop("strict", False), today=TODAY)


class CleanTests(unittest.TestCase):
    def test_removes_invisible_and_tatweel(self):
        out = pp.clean_text("مرحبـا\u200b بك\r\n\r\n\r\n\r\nنهاية   \n")
        self.assertNotIn("\u200b", out)
        self.assertNotIn("\u0640", out)
        self.assertNotIn("\r", out)
        self.assertNotIn("\n\n\n", out)


class ValidationTests(unittest.TestCase):
    def test_good_file_passes_and_keeps_metadata_per_chunk(self):
        _, _, chunks, report = run(GOOD)
        self.assertEqual(report.errors, [])
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["metadata"]["product_id"], "test-card")
        self.assertEqual(chunks[1]["metadata"]["category"], "not_available")
        self.assertNotIn("```", chunks[0]["text"])  # metadata block is not part of the text

    def test_missing_key(self):
        _, _, chunks, report = run(GOOD.replace("category: credit_cards\n", ""))
        self.assertTrue(any("missing metadata keys" in e for e in report.errors))
        self.assertEqual(chunks, [])

    def test_unknown_category(self):
        _, _, _, report = run(GOOD.replace("credit_cards", "crypto"))
        self.assertTrue(any("unknown category" in e for e in report.errors))

    def test_bad_date_and_future_date(self):
        _, _, _, r1 = run(GOOD.replace("2026-11-13", "13-11-2026"))
        self.assertTrue(any("ISO date" in e for e in r1.errors))
        _, _, _, r2 = run(GOOD.replace("2026-11-13", "2027-01-01"))
        self.assertTrue(any("future" in e for e in r2.errors))

    def test_bad_source_and_id(self):
        _, _, _, r1 = run(GOOD.replace("https://www.cibeg.com/", "https://example.com/"))
        self.assertTrue(any("source must start" in e for e in r1.errors))
        _, _, _, r2 = run(GOOD.replace("test-card", "Test_Card"))
        self.assertTrue(any("kebab-case" in e for e in r2.errors))

    def test_duplicate_ids(self):
        dup = GOOD + "\n## قسم ثان\n\n```yaml\nproduct_id: test-card\nproduct_name_en: B\ncategory: loans\nlanguage: ar\nsource: https://www.cibeg.com/x\nlast_verified: 2026-11-13\n```\n\n- نص\n"
        _, _, _, report = run(dup)
        self.assertTrue(any("duplicate product_id" in e for e in report.errors))

    def test_stale_warning_and_strict(self):
        _, _, _, report = pp.process_text(GOOD, 1000, 3, False, today=TODAY)
        self.assertTrue(any("days old" in w for w in report.warnings))
        _, _, _, strict = pp.process_text(GOOD, 1000, 3, True, today=TODAY)
        self.assertTrue(any("--strict" in e for e in strict.errors))

    def test_section_without_metadata_is_an_error(self):
        _, _, _, report = run(GOOD + "\n## قسم بلا بيانات\n\n- نص\n")
        self.assertTrue(any("missing metadata block" in e for e in report.errors))


class ChunkTests(unittest.TestCase):
    def test_long_section_is_split_and_title_repeated(self):
        bullets = "\n".join(f"- بند رقم {i} " + "كلمة " * 20 for i in range(12))
        text = GOOD.replace("- نقطة أولى\n- نقطة ثانية", bullets)
        _, _, chunks, report = run(text, max_chars=400)
        self.assertEqual(report.errors, [])
        card = [c for c in chunks if c["metadata"]["product_id"] == "test-card"]
        self.assertGreater(len(card), 1)
        for c in card:
            self.assertTrue(c["text"].startswith("بطاقة تجريبية"))
            self.assertLessEqual(c["char_count"], 400 + 120)  # one bullet may exceed slightly
        self.assertEqual({c["metadata"]["parts_total"] for c in card}, {len(card)})
        self.assertEqual(len({c["chunk_id"] for c in chunks}), len(chunks))


if __name__ == "__main__":
    unittest.main()
