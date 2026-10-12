"""The viewer page builder."""

import re

from agentcad.templating import Page


def _ids(html):
    return re.findall(r'data-variant-id="(\d+)"', html)


def test_a_page_numbers_its_own_variants_from_one():
    """Variant ids are the page's, not the process's: the same session gives the same page however many pages
    were built before it (a counter on the class once made the second page in a process start at 3)."""
    pages = []
    for _ in range(2):
        page = Page("t")
        page.variant("v1")
        page.variant("v2")
        pages.append(page.build())
    assert _ids(pages[0]) == _ids(pages[1]) == ["1", "2"]
    assert pages[0] == pages[1]
