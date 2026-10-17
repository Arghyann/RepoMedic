import pytest

from repomedic.mcp_server.editing import EditError
from repomedic.mcp_server.symbols import add_imports, replace_symbol, symbol_source

SRC = '''"""Cart."""
import json


def add_to_cart(product_id, quantity=1, items=[]):
    items.append(product_id)
    return items


class Store:
    def total(self):
        return 1
'''


def test_replace_function_keeps_rest_of_file():
    out = replace_symbol(SRC, "add_to_cart", """
def add_to_cart(product_id, quantity=1, items=None):
    if items is None:
        items = []
    items.append(product_id)
    return items
""")
    assert "items=None" in out and "class Store" in out and out.count("def add_to_cart") == 1
    compile(out, "x", "exec")


def test_replace_method_reindents():
    out = replace_symbol(SRC, "Store.total", "def total(self):\n    return 2")
    assert "    def total(self):\n        return 2\n" in out


def test_rejects_wrong_symbol_and_partial_code():
    with pytest.raises(EditError):
        replace_symbol(SRC, "nope", "def nope(): pass")
    with pytest.raises(EditError):
        replace_symbol(SRC, "add_to_cart", "items = []")


def test_symbol_source_and_imports():
    assert symbol_source(SRC, "Store.total").strip().startswith("def total")
    out = add_imports(SRC, ["import os", "import json"])
    assert out.count("import json") == 1 and "import os" in out
