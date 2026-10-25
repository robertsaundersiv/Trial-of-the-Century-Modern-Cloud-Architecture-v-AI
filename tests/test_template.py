"""Checks that cloudformation.yaml carries the same Lambda code as src/ and stays inside the inline-code limit."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE_INDENT = " " * 10


def inline_code():
    template = (ROOT / "cloudformation.yaml").read_text(encoding="utf-8")
    block = re.search(r"ZipFile: \|\n(.*?)\n\nOutputs:", template, re.S).group(1)
    return "\n".join(line.removeprefix(INLINE_INDENT) for line in block.split("\n")) + "\n"


class TemplateTest(unittest.TestCase):
    def test_inline_code_matches_source(self):
        source = (ROOT / "src" / "summarize_function" / "lambda_function.py").read_text(encoding="utf-8")
        self.assertEqual(inline_code(), source)

    def test_inline_code_under_zipfile_limit(self):
        # CloudFormation rejects inline Lambda code longer than 4096 characters.
        self.assertLessEqual(len(inline_code()), 4096)


if __name__ == "__main__":
    unittest.main()
