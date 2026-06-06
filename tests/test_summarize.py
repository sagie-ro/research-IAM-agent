def test_structure_digest_has_modules_entries_and_types(toolbox):
    digest = toolbox.structure_digest()
    assert "module map" in digest
    assert "entry points" in digest
    # at least one key type from the sample repo is surfaced
    assert "Animal" in digest or "Service" in digest
    # README head is included
    assert "Demo" in digest


def test_structure_digest_is_bounded(toolbox):
    assert len(toolbox.structure_digest()) <= 6000
