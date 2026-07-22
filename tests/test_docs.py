from tools import check_docs


def test_document_checker_validates_targets_and_anchors(tmp_path):
    guide = tmp_path / "guide.md"
    guide.write_text("# Guide\n\n## Repeated heading\n\n## Repeated heading\n", encoding="utf-8")
    index = tmp_path / "README.md"
    index.write_text("[guide](guide.md#repeated-heading-1)\n", encoding="utf-8")
    assert check_docs.check_documents(tmp_path, [index, guide]) == []


def test_document_checker_reports_missing_targets_and_anchors(tmp_path):
    index = tmp_path / "README.md"
    index.write_text(
        "# Index\n\n[missing](missing.md)\n[bad anchor](#not-here)\n",
        encoding="utf-8",
    )
    errors = check_docs.check_documents(tmp_path, [index])
    assert any("missing local target" in error for error in errors)
    assert any("missing local anchor" in error for error in errors)
