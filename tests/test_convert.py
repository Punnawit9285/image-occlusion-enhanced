"""
Round trips between this add-on's notes and Anki's Image Occlusion, run on a
real (temporary) collection. Needs the anki package; skipped without it.
"""

import os
import struct
import time
import zlib
from xml.dom import minidom

import pytest

from conftest import DATA

anki = pytest.importorskip("anki")
from anki.collection import Collection  # noqa: E402

from image_occlusion_enhanced import convert, masks, native  # noqa: E402
from image_occlusion_enhanced.consts import (  # noqa: E402
    IO_CARD_NAME,
    IO_FLDS,
    IO_FLDS_IDS,
    IO_MODEL_NAME,
)

SVG = (DATA / "sample-original-mask.svg").read_text()
UNIQ = "e7dd28558d524ad2a95558d2633ecd48"
SETTINGS = convert.Settings()


def png(width, height):
    """A blank PNG of the given size"""
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def col(tmp_path):
    col = Collection(str(tmp_path / "collection.anki2"))
    notetype = col.models.new(IO_MODEL_NAME)
    for key in IO_FLDS_IDS:
        col.models.add_field(notetype, col.models.new_field(IO_FLDS[key]))
    template = col.models.new_template(IO_CARD_NAME)
    template["qfmt"] = "{{%s}}{{%s}}" % (IO_FLDS["im"], IO_FLDS["qm"])
    template["afmt"] = "{{%s}}{{%s}}" % (IO_FLDS["im"], IO_FLDS["am"])
    col.models.add_template(notetype, template)
    col.models.add(notetype)
    col.media.write_data("sample.png", png(800, 600))
    yield col
    col.close()


def add_ioe_set(col, svg=SVG, mode="ao", skip=()):
    """Add the notes the editor would make for svg; returns {note ID: note}"""
    notetype = col.models.by_name(IO_MODEL_NAME)
    svg = svg.replace("-ao-", "-%s-" % mode)
    occl_id = "%s-%s" % (UNIQ, mode)
    omask = col.media.write_data(masks.mask_file_name(occl_id, "r1", "O"), svg.encode())
    layer = masks.mask_layer(minidom.parseString(svg.encode()).documentElement)
    positions = {
        n.getAttribute("id"): i
        for i, n in enumerate(layer.childNodes)
        if n.nodeType == n.ELEMENT_NODE and n.hasAttribute("id")
    }
    ids = masks.mask_ids(svg)
    indexes = [positions[i] for i in ids]
    if mode == "ag":
        ids = ["%s-0" % occl_id]
    notes = {}
    for note_id in ids:
        if note_id in skip:
            continue
        target = None if mode == "ag" else positions[note_id]
        files = {}
        for side in "QA":
            content = masks.build_mask(svg, mode, side, indexes, target, "#FF7E7E")
            files[side] = col.media.write_data(
                masks.mask_file_name(note_id, "r1", side), content.encode()
            )
        note = col.new_note(notetype)
        note[IO_FLDS["id"]] = note_id
        note[IO_FLDS["hd"]] = "Knee"
        note[IO_FLDS["im"]] = '<img src="sample.png" />'
        note[IO_FLDS["qm"]] = '<img src="%s" />' % files["Q"]
        note[IO_FLDS["am"]] = '<img src="%s" />' % files["A"]
        note[IO_FLDS["om"]] = '<img src="%s" />' % omask
        note[IO_FLDS["rk"]] = "remark"
        note.tags = ["anatomy"]
        col.add_note(note, 1)
        notes[note_id] = note
    return notes


def review(col, card, interval, reps):
    """Give a card review history and a review-state schedule"""
    card.type = card.queue = 2
    card.ivl = interval
    card.due = col.sched.today + interval
    card.reps = reps
    card.factor = 2500
    col.update_card(card)
    now = int(time.time() * 1000)
    for i in range(reps):
        col.db.execute(
            "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) values (?,?,?,?,?,?,?,?,?)",
            now + card.id % 100000 * 100 + i,
            card.id,
            -1,
            3,
            interval,
            1,
            2500,
            5000,
            1,
        )


def revlog_count(col, cid):
    return col.db.scalar("select count() from revlog where cid = ?", cid)


def test_ioe_to_native_and_back(col):
    notes = add_ioe_set(col)
    cards = {note_id: note.cards()[0] for note_id, note in notes.items()}
    third = "%s-ao-3" % UNIQ
    review(col, cards[third], 12, 4)

    report = convert.ioe_to_native(col, [notes[third].id], SETTINGS)
    assert report.skipped == []
    assert (
        report.images,
        report.notes_removed,
        report.notes_created,
        report.cards_moved,
    ) == (1, 6, 1, 6)
    assert not col.find_notes('"note:%s"' % IO_MODEL_NAME)
    assert report.unused_media and all(
        name.endswith(".svg") for name in report.unused_media
    )

    (nid,) = col.find_notes("note:Image*")
    note = col.get_note(nid)
    assert note["Header"] == "Knee"
    assert "<b>Remarks</b><br>remark" in note["Back Extra"]
    assert note.tags == ["anatomy"]
    # the image has a drawn line, which needs a painter to be kept
    assert (
        report.left_out["images with lines or other drawings that could not be kept"]
        == 1
    )
    shapes = native.parse_occlusions(note["Occlusion"])
    assert sorted({s.ordinal for s in shapes}) == [0, 1, 2, 3, 4, 5, 6]
    native_cards = {c.ord: c for c in note.cards()}
    assert len(native_cards) == 6
    moved = native_cards[2]
    assert (moved.ivl, moved.reps, moved.type) == (12, 4, 2)
    assert revlog_count(col, moved.id) == 4
    assert revlog_count(col, cards[third].id) == 0
    # Anki reads the note back without complaint
    parsed = col.get_image_occlusion_note(note_id=nid)
    assert not parsed.HasField("error")
    assert len(parsed.note.occlusions) == 7

    back = convert.native_to_ioe(col, [nid], SETTINGS)
    assert back.skipped == []
    assert (back.notes_created, back.cards_moved, back.notes_removed) == (6, 6, 1)
    ioe = [col.get_note(n) for n in col.find_notes('"note:%s"' % IO_MODEL_NAME)]
    by_nr = {int(n[IO_FLDS["id"]].rsplit("-", 1)[1]): n for n in ioe}
    assert sorted(by_nr) == [1, 2, 3, 4, 5, 6]
    card = by_nr[3].cards()[0]
    assert (card.ivl, card.reps) == (12, 4)
    assert revlog_count(col, card.id) == 4
    for note in ioe:
        for key in ("qm", "am", "om"):
            name = convert.media_name(note[IO_FLDS[key]])
            assert os.path.isfile(os.path.join(col.media.dir(), name)), name
        assert note[IO_FLDS["rk"]].startswith("<b>Remarks</b>")
        assert note[IO_FLDS["id"]].split("-")[1] == "ao"


def test_hide_one_guess_one_round_trip_shares_answer(col):
    notes = add_ioe_set(col, mode="oa")
    report = convert.ioe_to_native(col, [next(iter(notes.values())).id], SETTINGS)
    assert report.notes_created == 1
    (nid,) = col.find_notes("note:Image*")
    assert all(
        "oi" not in s.props
        for s in native.parse_occlusions(col.get_note(nid)["Occlusion"])
    )
    convert.native_to_ioe(col, [nid], SETTINGS)
    ioe = [col.get_note(n) for n in col.find_notes('"note:%s"' % IO_MODEL_NAME)]
    assert len(ioe) == 6
    answers = {n[IO_FLDS["am"]] for n in ioe}
    assert len(answers) == 1  # one answer file for all cards
    assert {n[IO_FLDS["id"]].split("-")[1] for n in ioe} == {"oa"}


def test_hide_all_guess_all_round_trip(col):
    notes = add_ioe_set(col, mode="ag")
    assert len(notes) == 1
    note = next(iter(notes.values()))
    review(col, note.cards()[0], 5, 2)
    report = convert.ioe_to_native(col, [note.id], SETTINGS)
    assert report.skipped == [] and report.cards_moved == 1
    (nid,) = col.find_notes("note:Image*")
    assert len(col.get_note(nid).cards()) == 1
    back = convert.native_to_ioe(col, [nid], SETTINGS)
    assert back.notes_created == 1
    (ioe_nid,) = col.find_notes('"note:%s"' % IO_MODEL_NAME)
    ioe = col.get_note(ioe_nid)
    assert ioe[IO_FLDS["id"]].endswith("-ag-0")
    assert ioe.cards()[0].ivl == 5
    omask = open(
        os.path.join(col.media.dir(), convert.media_name(ioe[IO_FLDS["om"]]))
    ).read()
    assert len(masks.mask_ids(omask)) == 7  # the group became two masks


def test_deleted_cards_are_left_out(col):
    deleted = "%s-ao-2" % UNIQ
    notes = add_ioe_set(col, skip=(deleted,))
    report = convert.ioe_to_native(col, [next(iter(notes.values())).id], SETTINGS)
    assert report.cards_moved == 5
    assert report.left_out["masks whose card was deleted"] == 1


def test_missing_mask_file_skips_the_image(col):
    notes = add_ioe_set(col)
    first = next(iter(notes.values()))
    os.remove(os.path.join(col.media.dir(), convert.media_name(first[IO_FLDS["om"]])))
    report = convert.ioe_to_native(col, [first.id], SETTINGS)
    assert report.images == 0
    assert len(report.skipped) == 1 and "original mask" in report.skipped[0]
    assert len(col.find_notes('"note:%s"' % IO_MODEL_NAME)) == 6


def test_painted_annotations_replace_the_image(col):
    notes = add_ioe_set(col)
    painted = []

    def paint(col, image, svg):
        painted.append((image, svg))
        return col.media.write_data("sample-annotated.png", png(800, 600))

    report = convert.ioe_to_native(
        col, [next(iter(notes.values())).id], SETTINGS, paint
    )
    assert painted and painted[0][0] == "sample.png" and "<line" in painted[0][1]
    assert not report.left_out
    (nid,) = col.find_notes("note:Image*")
    assert "sample-annotated.png" in col.get_note(nid)["Image"]


def test_native_with_empty_card(col):
    notetype = convert.native_notetype(col)
    note = col.new_note(notetype)
    note["Occlusion"] = (
        "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:oi=1}}"
        "{{c2::image-occlusion:rect:left=.5:top=.5:width=.2:height=.2:oi=1}}"
    )
    note["Image"] = '<img src="sample.png">'
    col.add_note(note, 1)
    assert len(note.cards()) == 2
    note["Occlusion"] = (
        "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:oi=1}}"
    )
    col.update_note(note)
    assert len(note.cards()) == 2  # Anki keeps the card until Empty Cards
    report = convert.native_to_ioe(col, [note.id], SETTINGS)
    assert report.skipped == []
    assert report.left_out["empty cards"] == 1
    assert report.notes_created == 1


def test_native_with_missing_image_is_skipped(col):
    notetype = convert.native_notetype(col)
    note = col.new_note(notetype)
    note["Occlusion"] = (
        "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:oi=1}}"
    )
    note["Image"] = '<img src="gone.png">'
    col.add_note(note, 1)
    report = convert.native_to_ioe(col, [note.id], SETTINGS)
    assert report.notes_created == 0 and "gone.png" in report.skipped[0]
    assert col.get_note(note.id)  # left alone
