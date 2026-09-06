from pathlib import Path

import pytest

from tools.bundle.release_notes import render_notes


def test_release_notes_bind_local_links_to_tag():
    notes = render_notes(Path(__file__).resolve().parents[1], "v0.4.0")
    assert "blob/v0.4.0/docs/INSTALLATION.md" in notes
    assert "blob/v0.4.0/ROADMAP.md" in notes
    assert "releases/tag/v0.4.0" in notes
    assert "](INSTALLATION.md)" not in notes


def test_release_notes_missing_tag_refuses(tmp_path):
    with pytest.raises(ValueError, match="missing release notes"):
        render_notes(tmp_path, "v0.5.0")


@pytest.mark.parametrize("tag", ["main", "v0.4", "../v0.4.0", "v0.4.0/extra"])
def test_release_notes_reject_nonrelease_tag(tmp_path, tag):
    with pytest.raises(ValueError, match="release tag"):
        render_notes(tmp_path, tag)


def test_release_notes_reject_escape_link(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "RELEASE_0_4_0.md").write_text("[bad](../../secret)", encoding="utf-8")
    with pytest.raises(ValueError, match="leaves repository"):
        render_notes(tmp_path, "v0.4.0")
