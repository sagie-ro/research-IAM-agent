def test_inventory_classifies_files(built_index):
    index, _ = built_index
    by_path = {f.relpath: f for f in index.files}
    assert by_path["pkg/mod.py"].language == "python"
    assert by_path["Service.java"].language == "java"
    assert by_path["README.md"].language == "doc"
    # binary asset is inventoried but not parsed
    asset = by_path["asset.bin"]
    assert asset.language == "binary" and asset.n_lines == 0


def test_symbols_entries_and_resolution(built_index):
    index, _ = built_index
    names = {s.name for s in index.symbols}
    assert {"Animal", "Dog", "bark", "main"} <= names
    assert any(s.is_entry for s in index.symbols)
    # unique-name calls resolve (bark / noise); ambiguous (speak x2) stays unlinked
    assert any(e.type == "calls" and e.dst_id for e in index.edges)
    assert any(e.type == "extends" for e in index.edges)


def test_call_paths_from_entries(built_index):
    index, _ = built_index
    assert index.call_paths, "expected precomputed call-paths from entry points"


def test_schema_round_trips(built_index):
    import sqlite3

    _, db = built_index
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "3"
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] >= 4
    finally:
        con.close()


def test_content_hash_populated(built_index):
    index, _ = built_index
    by_path = {f.relpath: f for f in index.files}
    assert by_path["pkg/mod.py"].content_hash      # source files are hashed (delta key)
    assert by_path["README.md"].content_hash       # docs too
    assert by_path["asset.bin"].content_hash == ""  # inventory-only, never read


def test_docs_are_chunked(built_index):
    index, _ = built_index
    by_file = {}
    for c in index.doc_chunks:
        by_file.setdefault(c.file_id, []).append(c)
    assert "docs/guide.md" in by_file and "README.md" in by_file
    headings = {c.heading for c in by_file["docs/guide.md"]}
    assert "Dogs" in headings and "Design notes" in headings
