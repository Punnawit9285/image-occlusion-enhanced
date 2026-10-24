import pytest

anki = pytest.importorskip("anki")
from anki.collection import Collection  # noqa: E402

from image_occlusion_enhanced import mediacleanup  # noqa: E402


@pytest.fixture
def col(tmp_path):
    col = Collection(str(tmp_path / "collection.anki2"))
    yield col
    col.close()


def test_only_unused_files_are_trashed(col):
    for name in ("used-q.svg", "old-q.svg", "shared-a.svg", "photo.png"):
        col.media.write_data(name, b"<svg/>")
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = '<img src="used-q.svg" /> <img src=\'shared-a.svg\'>'
    col.add_note(note, 1)
    trashed = mediacleanup.trash_unused(
        col, ["used-q.svg", "old-q.svg", "shared-a.svg", "missing.svg"]
    )
    assert trashed == ["old-q.svg"]
    assert col.media.have("used-q.svg") and col.media.have("shared-a.svg")
    assert not col.media.have("old-q.svg")
    assert col.media.have("photo.png")


def test_used_names_decodes_entities(col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = '<img src="a&amp;b.svg">'
    col.add_note(note, 1)
    assert "a&b.svg" in mediacleanup.used_names(col)
