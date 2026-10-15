import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render  # noqa: E402


@pytest.fixture
def stock_text():
    return render.STOCK_REFERENCE.read_text()


@pytest.fixture
def make_tree():
    """Factory for temporary templates trees; all are removed after the test."""
    trees = []

    def factory(**kwargs):
        tree = render.TemplateTree(**kwargs)
        trees.append(tree)
        return tree

    yield factory
    for tree in trees:
        tree.close()
