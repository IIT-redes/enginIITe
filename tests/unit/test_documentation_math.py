"""The formulas of the documentation must render on GitHub as well as in the built pages.

GitHub draws the formulas of a Markdown file with its own math engine, which is stricter than the one of the built
documentation. A `#` inside a formula, or an escape inside `\text{...}`, appears there as an error box instead of a
formula. These tests read the Markdown files and check the rules that avoid those errors.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted(p for p in (ROOT / 'docs').rglob('*.md') if '_build' not in p.parts) + [ROOT / 'README.md']
FENCE = re.compile('`{3}.*?`{3}', re.S)
DISPLAY = re.compile(r'\$\$(.+?)\$\$', re.S)
INLINE = re.compile(r'(?<![$\\])\$([^$\n]+?)\$(?!\$)')
TEXT_ARGUMENT = re.compile(r'\\text\{((?:[^{}]|\{[^{}]*\})*)\}')


def formulas(path):
    """Every formula of a file as (line, kind, body), without the code blocks."""
    text = FENCE.sub(lambda m: '\n' * m.group(0).count('\n'), path.read_text(encoding='utf-8'))
    found = [(text[:m.start()].count('\n') + 1, 'display', m.group(1)) for m in DISPLAY.finditer(text)]
    rest = DISPLAY.sub(lambda m: '\n' * m.group(0).count('\n'), text)
    found += [(rest[:m.start()].count('\n') + 1, 'inline', m.group(1)) for m in INLINE.finditer(rest)]
    return found


class FormulaRulesTests(unittest.TestCase):
    def check(self, rule, message):
        problems = []
        for path in FILES:
            for line, kind, body in formulas(path):
                if rule(body):
                    problems.append('%s:%d %s' % (path.relative_to(ROOT).as_posix(), line, ' '.join(body.split())[:70]))
        self.assertEqual(problems, [], message)

    def test_there_are_formulas_to_check(self):
        self.assertGreater(sum(len(formulas(p)) for p in FILES), 100)

    def test_no_formula_contains_a_hash_sign(self):
        self.check(lambda body: '#' in body, 'a # inside a formula is an error on GitHub, name equations without it')

    def test_no_text_in_a_formula_contains_an_escape(self):
        def has_escape(body):
            return any('\\' in argument for argument in TEXT_ARGUMENT.findall(body))
        self.check(has_escape, 'an escape inside \\text{...} is not processed on GitHub, use plain characters')

    def test_inline_formulas_have_no_space_next_to_the_dollar_signs(self):
        problems = []
        for path in FILES:
            for line, kind, body in formulas(path):
                if kind == 'inline' and body != body.strip():
                    problems.append('%s:%d' % (path.relative_to(ROOT).as_posix(), line))
        self.assertEqual(problems, [], 'GitHub does not draw $ x $ with spaces inside the dollar signs')

    def test_no_formula_has_a_less_than_sign_followed_by_a_letter(self):
        self.check(lambda body: re.search('<[A-Za-z/]', body) is not None, 'GitHub may read it as an HTML tag, write \\lt or add a space')


if __name__ == '__main__':
    unittest.main()
