def test_get_symbol(toolbox):
    assert "Animal" in toolbox.get_symbol("Animal")
    assert "no symbol" in toolbox.get_symbol("DoesNotExist")


def test_find_files_lists_binary_asset(toolbox):
    out = toolbox.find_files("asset")
    assert "asset.bin" in out and "binary" in out


def test_read_file_with_line_numbers(toolbox):
    out = toolbox.read_file("pkg/mod.py", 1, 6)
    assert "pkg/mod.py:1-6" in out and "class Animal" in out


def test_read_file_refuses_traversal(toolbox):
    assert "refused" in toolbox.read_file("../../etc/passwd", 1, 5)


def test_get_call_path_for_entry(toolbox):
    out = toolbox.get_call_path("main")
    assert "call-path from entry" in out


def test_search_lexical(toolbox):
    out = toolbox.search_lexical("class Animal")
    assert "Animal" in out


def test_search_docs_finds_section(toolbox):
    out = toolbox.search_docs("dog barks")
    assert "docs/guide.md" in out and "Dogs" in out
    assert "authoritative" in out  # the code-wins disclaimer travels with the result


def test_search_docs_no_match(toolbox):
    assert "no matches for" in toolbox.search_docs("kubernetes helm chart")
