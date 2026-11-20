"""Checks that the relative links of the Markdown documentation point to files that exist.

Run them from the repository folder, the one that contains pyproject.toml.

    python -m unittest discover -s tests/unit
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r'\]\(([^)\s]+)\)')


def markdown_files():
    files = [ROOT / 'README.md', ROOT / 'CONTRIBUTING.md', ROOT / 'CHANGELOG.md', ROOT / 'scripts' / 'README.md']
    files += sorted((ROOT / 'docs').rglob('*.md'))
    return [f for f in files if f.is_file()]


class DocumentationLinkTests(unittest.TestCase):
    def test_there_are_pages_to_check(self):
        self.assertGreaterEqual(len(markdown_files()), 5)

    def test_relative_links_resolve(self):
        broken = []
        for page in markdown_files():
            for target in LINK.findall(page.read_text(encoding='utf-8')):
                if target.startswith(('http://', 'https://', 'mailto:', '#')):
                    continue
                path = target.split('#')[0]
                if path and not (page.parent / path).resolve().exists():
                    broken.append('%s -> %s' % (page.relative_to(ROOT), target))
        self.assertEqual(broken, [], 'broken links')


if __name__ == '__main__':
    unittest.main()
