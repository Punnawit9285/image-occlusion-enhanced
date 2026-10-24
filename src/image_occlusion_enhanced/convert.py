# -*- coding: utf-8 -*-

# Image Occlusion Enhanced Add-on for Anki
#
# Copyright (C) 2026  Punnawit9285 <https://github.com/Punnawit9285>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version, with the additions
# listed at the end of the license file that accompanied this program.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# NOTE: This program is subject to certain additional terms pursuant to
# Section 7 of the GNU Affero General Public License.  You should have
# received a copy of these additional terms immediately following the
# terms and conditions of the GNU Affero General Public License that
# accompanied this program.

"""
Moves notes between this add-on and the Image Occlusion built into Anki
23.10 and later, together with their scheduling and review history.

Uses nothing but the collection, so that it can run in a background thread
and be tested without Anki's GUI.

A conversion cannot be undone from Anki's Edit menu: review history is moved
to the new cards with SQL, and Anki clears its undo history after that. The
GUI makes a backup first and has Anki ask for a full sync.
"""

import html
import os
import re
import urllib.parse
import uuid
from collections import Counter, OrderedDict
from typing import Callable, Dict, Iterable, List, Optional, Set
from xml.dom import minidom

from . import masks, native
from .consts import IO_FLDS, IO_MODEL_NAME
from .masks import (
    HIDE_ALL_GUESS_ALL,
    HIDE_ONE_GUESS_ONE,
    NOTE_ID_RE,
)
from .utils import get_image_dimensions

# The roles Anki gives the fields of its Image Occlusion note type. They are
# kept in each field's "tag", which survives renaming the fields.
NATIVE_OCCLUSION, NATIVE_IMAGE, NATIVE_HEADER, NATIVE_BACK_EXTRA, NATIVE_COMMENTS = (
    range(5)
)

_IMAGE_OCCLUSION_KIND = 6  # StockNotetype.OriginalStockKind.IMAGE_OCCLUSION

# Card properties that make up its scheduling. Newer Anki versions have more
# of them; whatever a version lacks is skipped.
SCHEDULING = (
    "did",
    "odid",
    "type",
    "queue",
    "due",
    "odue",
    "ivl",
    "factor",
    "reps",
    "lapses",
    "left",
    "flags",
    "original_position",
    "custom_data",
    "memory_state",
    "desired_retention",
    "decay",
    "last_review_time",
)

_IMG_SRC_RE = re.compile(r"""<img[^>]*?\ssrc=(["'])(.*?)\1""", re.I | re.S)


class Settings:
    """The parts of the add-on's settings a conversion needs"""

    def __init__(self, conf: Optional[dict] = None):
        conf = conf or {}
        self.fields: Dict[str, str] = dict(IO_FLDS)
        self.fields.update(conf.get("flds") or {})
        self.ofill = "#" + str(conf.get("ofill", "FFEBA2")).lstrip("#")
        self.qfill = "#" + str(conf.get("qfill", "FF7E7E")).lstrip("#")
        self.scol = "#" + str(conf.get("scol", "2D2D2D")).lstrip("#")
        self.swidth = conf.get("swidth", 3)
        self.font = conf.get("font", "Arial")


class Report:
    """What a conversion did"""

    def __init__(self):
        self.images = 0  # images (sets of notes) converted
        self.notes_removed = 0
        self.notes_created = 0
        self.cards_moved = 0
        # one line per image or note that was left as it was, and why
        self.skipped: List[str] = []
        # descriptions of details the target format cannot hold -> count
        self.left_out: Counter = Counter()
        # mask files no longer used by the converted notes
        self.unused_media: Set[str] = set()


class _Skip(Exception):
    pass


# Helpers ------------------------------------------------------------------------


def media_name(field_html: str) -> Optional[str]:
    match = _IMG_SRC_RE.search(field_html or "")
    return html.unescape(match.group(2)) if match else None


def _media_path(col, name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    for candidate in (name, urllib.parse.unquote(name)):
        path = os.path.join(col.media.dir(), candidate)
        if os.path.isfile(path):
            return path
    return None


def _img(name: str, closing: str = "") -> str:
    return '<img src="%s"%s>' % (html.escape(name, quote=True), closing)


def _field_search(field: str, value: str) -> str:
    """A search for notes whose field matches value ("*" is a wildcard)"""
    escaped = re.sub(r'([\\"*_:])', r"\\\1", field)
    return '"%s:%s"' % (escaped, value)


def _home_deck(card) -> int:
    """The deck a card belongs to, also while it is in a filtered deck"""
    return card.odid or card.did


def copy_scheduling(col, source, target) -> None:
    """Give target the scheduling and review history of source"""
    for name in SCHEDULING:
        if hasattr(source, name) and hasattr(target, name):
            setattr(target, name, getattr(source, name))
    try:
        col.update_card(target, skip_undo_entry=True)
    except TypeError:  # Anki < 2.1.45
        col.update_card(target)
    # There is no API for this. Anki clears its undo history after any SQL,
    # so the conversion cannot be half undone afterwards.
    col.db.execute(
        "update revlog set cid = ?, usn = -1 where cid = ?", target.id, source.id
    )


def supports_native(col) -> bool:
    return hasattr(col, "add_image_occlusion_notetype")


def is_native_notetype(notetype) -> bool:
    return bool(notetype) and notetype.get("originalStockKind") == _IMAGE_OCCLUSION_KIND


def native_notetype(col):
    """Anki's Image Occlusion note type, added to the collection if needed"""
    for notetype in col.models.all():
        if is_native_notetype(notetype) and notetype.get("name") == "Image Occlusion":
            return notetype
    for notetype in col.models.all():
        if is_native_notetype(notetype):
            return notetype
    col.add_image_occlusion_notetype()
    for notetype in col.models.all():
        if is_native_notetype(notetype):
            return notetype
    raise RuntimeError("could not add Anki's Image Occlusion note type")


def _native_field_indexes(notetype) -> Dict[int, int]:
    """field role (NATIVE_*) -> field index"""
    indexes = {}
    for index, field in enumerate(notetype["flds"]):
        role = field.get("tag")
        indexes[role if role is not None else index] = index
    return indexes


def _ioe_notetype(col):
    notetype = col.models.by_name(IO_MODEL_NAME)
    if not notetype:
        raise RuntimeError("the %s note type is missing" % IO_MODEL_NAME)
    return notetype


# To Anki's Image Occlusion ------------------------------------------------------


def ioe_sets(
    col, note_ids: Iterable[int], settings: Settings
) -> "OrderedDict[str, Dict[str, object]]":
    """The notes of each image the given notes belong to, so that an image
    is always converted as a whole: occlusion ID -> {note ID: note}"""
    notetype = _ioe_notetype(col)
    id_field = settings.fields["id"]
    sets: "OrderedDict[str, Dict[str, object]]" = OrderedDict()
    for nid in note_ids:
        note = col.get_note(nid)
        if note.mid != notetype["id"]:
            continue
        match = NOTE_ID_RE.match(note[id_field] if id_field in note else "")
        if not match:
            continue
        occl_id = "%s-%s" % (match.group("uniq"), match.group("mode"))
        if occl_id in sets:
            continue
        siblings: Dict[str, object] = OrderedDict()
        for sibling_id in col.find_notes(_field_search(id_field, occl_id + "-*")):
            sibling = col.get_note(sibling_id)
            if sibling.mid != notetype["id"]:
                continue
            note_id = sibling[id_field]
            sibling_match = NOTE_ID_RE.match(note_id)
            if (
                sibling_match
                and "%s-%s" % (sibling_match.group("uniq"), sibling_match.group("mode"))
                == occl_id
            ):
                siblings[note_id] = sibling
        sets[occl_id] = siblings
    return sets


def _back_extra(note, settings: Settings) -> str:
    """The add-on's answer-side fields, combined into Back Extra"""
    parts = []
    footer = note[settings.fields["ft"]] if settings.fields["ft"] in note else ""
    if footer.strip():
        parts.append(footer)
    for key in ("rk", "sc", "e1", "e2"):
        name = settings.fields[key]
        if name in note and note[name].strip():
            parts.append("<b>%s</b><br>%s" % (html.escape(name), note[name]))
    return "<br><br>".join(parts)


def _ioe_set_to_native(
    col,
    notetype,
    occl_id: str,
    notes: Dict[str, object],
    settings: Settings,
    paint,
    report: Report,
) -> None:
    fields = settings.fields
    first = next(iter(notes.values()))
    mode = occl_id.rsplit("-", 1)[1]
    omask = media_name(first[fields["om"]])
    omask_path = _media_path(col, omask)
    if not omask_path:
        raise _Skip("its original mask file (%s) is missing" % (omask or "none"))
    image = media_name(first[fields["im"]])
    if not _media_path(col, image):
        raise _Skip("its image file (%s) is missing" % (image or "none"))
    with open(omask_path, encoding="utf-8") as f:
        svg = f.read()

    if mode == HIDE_ALL_GUESS_ALL:
        if len(notes) != 1:
            raise _Skip(
                "it has %d notes, but Hide All, Guess All makes one" % len(notes)
            )
        result = native.svg_to_native(svg, mode)
        ordinals = {note_id: 1 for note_id in notes}
    else:
        result = native.svg_to_native(svg, mode, set(notes))
        ordinals = dict(result.ordinals)
        missing = [note_id for note_id in notes if note_id not in ordinals]
        if missing:
            raise _Skip(
                "%d of its cards have no mask that could be converted" % len(missing)
            )
    if not any(shape.kind != "text" for shape in result.shapes):
        raise _Skip("it has no masks that could be converted")

    image_field = _img(image)
    if result.annotations:
        painted = paint(col, image, result.annotations) if paint else None
        if painted:
            image_field = _img(painted)
        else:
            result.left_out[
                "images with lines or other drawings that could not be kept"
            ] += 1

    note = col.new_note(notetype)
    indexes = _native_field_indexes(notetype)
    note.fields[indexes[NATIVE_OCCLUSION]] = result.occlusions
    note.fields[indexes[NATIVE_IMAGE]] = image_field
    if fields["hd"] in first:
        note.fields[indexes[NATIVE_HEADER]] = first[fields["hd"]]
    note.fields[indexes[NATIVE_BACK_EXTRA]] = _back_extra(first, settings)
    tags: List[str] = []
    for source in notes.values():
        tags.extend(t for t in source.tags if t not in tags)
    note.tags = tags
    source_cards = {note_id: source.cards()[0] for note_id, source in notes.items()}
    col.add_note(note, _home_deck(next(iter(source_cards.values()))))
    targets = {card.ord: card for card in note.cards()}
    for note_id, ordinal in ordinals.items():
        target = targets.get(ordinal - 1)
        if target is None:
            raise RuntimeError("card %d of the new note is missing" % ordinal)
        copy_scheduling(col, source_cards[note_id], target)
        report.cards_moved += 1

    for source in notes.values():
        for key in ("qm", "am", "om"):
            name = media_name(source[fields[key]]) if fields[key] in source else None
            if name:
                report.unused_media.add(name)
    col.remove_notes([source.id for source in notes.values()])
    report.left_out.update(result.left_out)
    report.images += 1
    report.notes_removed += len(notes)
    report.notes_created += 1


def ioe_to_native(
    col,
    note_ids: Iterable[int],
    settings: Settings,
    paint: Optional[Callable[[object, str, str], Optional[str]]] = None,
) -> Report:
    """Convert the images the given notes belong to into notes of Anki's
    Image Occlusion. paint(col, image, svg) can return the name of a copy of
    the image with drawings the built-in format cannot hold painted on."""
    report = Report()
    notetype = native_notetype(col)
    for occl_id, notes in ioe_sets(col, note_ids, settings).items():
        if not notes:
            continue
        try:
            _ioe_set_to_native(col, notetype, occl_id, notes, settings, paint, report)
        except (_Skip, ValueError) as e:
            first = next(iter(notes.values()))
            header = (
                re.sub(r"<[^>]+>", "", first[settings.fields["hd"]])
                if settings.fields["hd"] in first
                else ""
            )
            label = (
                '"%s"' % header.strip()[:40]
                if header.strip()
                else (media_name(first[settings.fields["im"]]) or occl_id)
            )
            report.skipped.append("%s was not converted: %s." % (label, e))
    return report


# From Anki's Image Occlusion -----------------------------------------------------


def _mask_indexes(svg: str) -> Dict[str, int]:
    """mask ID -> position among the mask layer's child nodes"""
    layer = masks.mask_layer(minidom.parseString(svg.encode("utf-8")).documentElement)
    return {
        node.getAttribute("id"): index
        for index, node in enumerate(layer.childNodes)
        if node.nodeType == node.ELEMENT_NODE and node.hasAttribute("id")
    }


def _native_note_to_ioe(
    col, notetype, note, settings: Settings, report: Report
) -> None:
    fields = settings.fields
    indexes = _native_field_indexes(note.note_type())
    occlusions = note.fields[indexes[NATIVE_OCCLUSION]]
    image = media_name(note.fields[indexes[NATIVE_IMAGE]])
    image_path = _media_path(col, image)
    if not image_path:
        raise _Skip("its image file (%s) is missing" % (image or "none"))
    try:
        width, height = get_image_dimensions(image_path)
    except Exception as e:
        raise _Skip("its image could not be read (%s)" % e)

    uniq_id = uuid.uuid4().hex
    result = native.native_to_svg(
        occlusions,
        width,
        height,
        uniq_id,
        fill=settings.ofill,
        stroke=settings.scol,
        stroke_width=settings.swidth,
        font_family=settings.font,
    )
    with_shapes = {
        s.ordinal
        for s in native.parse_occlusions(occlusions)
        if s.kind != "text" and s.ordinal > 0
    }
    cards = {card.ord + 1: card for card in note.cards()}
    for ordinal in cards:
        if ordinal not in result.note_ids:
            if ordinal in with_shapes:
                raise _Skip("card %d has no shape that could be converted" % ordinal)
            # a card whose shapes were all deleted; Anki shows it as empty
            report.left_out["empty cards"] += 1

    mode = result.mode
    occl_id = "%s-%s" % (uniq_id, mode)
    revision = masks.new_revision()
    svg = result.svg
    omask = col.media.write_data(
        masks.mask_file_name(occl_id, revision, "O"), svg.encode("utf-8")
    )
    positions = _mask_indexes(svg)
    mask_positions = [positions[i] for i in masks.mask_ids(svg)]

    shared_answer = None
    if mode == HIDE_ONE_GUESS_ONE:
        answer = masks.build_mask(svg, mode, "A", mask_positions, None, settings.qfill)
        shared_answer = col.media.write_data(
            masks.mask_file_name(occl_id, revision, "A"), answer.encode("utf-8")
        )

    image_field = _img(image, " /")
    header = note.fields[indexes[NATIVE_HEADER]]
    back_extra = note.fields[indexes[NATIVE_BACK_EXTRA]]
    comments = (
        note.fields[indexes[NATIVE_COMMENTS]] if NATIVE_COMMENTS in indexes else ""
    )
    for ordinal, note_id in result.note_ids.items():
        target_index = None if mode == HIDE_ALL_GUESS_ALL else positions[note_id]
        question = masks.build_mask(
            svg, mode, "Q", mask_positions, target_index, settings.qfill
        )
        qmask = col.media.write_data(
            masks.mask_file_name(note_id, revision, "Q"), question.encode("utf-8")
        )
        if shared_answer:
            amask = shared_answer
        else:
            answer = masks.build_mask(
                svg, mode, "A", mask_positions, target_index, settings.qfill
            )
            amask = col.media.write_data(
                masks.mask_file_name(note_id, revision, "A"), answer.encode("utf-8")
            )
        new = col.new_note(notetype)
        values = {
            "id": note_id,
            "hd": header,
            "im": image_field,
            "qm": _img(qmask, " /"),
            "am": _img(amask, " /"),
            "om": _img(omask, " /"),
            "rk": back_extra,
            "e1": comments,
        }
        for key, value in values.items():
            if fields[key] in new:
                new[fields[key]] = value
        new.tags = list(note.tags)
        source = cards.get(ordinal)
        col.add_note(new, _home_deck(source) if source else _home_deck(note.cards()[0]))
        report.notes_created += 1
        if source:
            copy_scheduling(col, source, new.cards()[0])
            report.cards_moved += 1
    col.remove_notes([note.id])
    report.images += 1
    report.notes_removed += 1


def native_to_ioe(col, note_ids: Iterable[int], settings: Settings) -> Report:
    """Convert notes of Anki's Image Occlusion into this add-on's notes"""
    report = Report()
    notetype = _ioe_notetype(col)
    for nid in note_ids:
        note = col.get_note(nid)
        if not is_native_notetype(note.note_type()):
            continue
        try:
            _native_note_to_ioe(col, notetype, note, settings, report)
        except (_Skip, ValueError) as e:
            indexes = _native_field_indexes(note.note_type())
            header = re.sub(r"<[^>]+>", "", note.fields[indexes[NATIVE_HEADER]]).strip()
            label = (
                '"%s"' % header[:40]
                if header
                else (media_name(note.fields[indexes[NATIVE_IMAGE]]) or "a note")
            )
            report.skipped.append("%s was not converted: %s." % (label, e))
    return report
