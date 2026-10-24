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
Browse window commands that convert notes between this add-on and the Image
Occlusion built into Anki 23.10 and later.
"""

import html
import os
from typing import Optional

from aqt import mw
from aqt.qt import QAction, QMenu

from . import convert, mediacleanup
from .compat import askUser, showInfo, showWarning
from .config import getColConfig, getOrCreateModel
from .lang import _
from .logger import logger
from .qt import qconnect


def paint_annotations(col, image: str, svg: str) -> Optional[str]:
    """Save a copy of the image with svg painted over it; returns its name.

    Used for drawings, such as lines and arrows, that the built-in Image
    Occlusion has no way to show.
    """
    try:
        from aqt.qt import QBuffer, QByteArray, QIODevice, QImage, QPainter, QRectF
        from PyQt6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    image_path = os.path.join(col.media.dir(), image)
    picture = QImage(image_path)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if picture.isNull() or not renderer.isValid():
        return None
    picture = picture.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(picture)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, picture.width(), picture.height()))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not picture.save(buffer, "PNG"):
        return None
    buffer.close()
    stem = os.path.splitext(image)[0]
    return col.media.write_data(stem + "-annotated.png", bytes(data))


def _changes():
    from anki.collection import OpChanges

    changes = OpChanges()
    for name in (
        "card",
        "note",
        "deck",
        "notetype",
        "note_text",
        "browser_table",
        "study_queues",
        "mtime",
    ):
        if hasattr(changes, name):
            setattr(changes, name, True)
    return changes


def _report_text(report: convert.Report, target: str) -> str:
    lines = [
        _("<b>{images} image(s) converted to {target}.</b>").format(
            images=report.images, target=target
        )
    ]
    if report.images:
        lines.append(
            _(
                "{removed} note(s) were replaced by {created} new one(s), and "
                "{cards} card(s) kept their scheduling and review history."
            ).format(
                removed=report.notes_removed,
                created=report.notes_created,
                cards=report.cards_moved,
            )
        )
    if report.left_out:
        lines.append(_("Left out:"))
        lines.append(
            "<br>".join(
                "&bull; %s: %d" % (html.escape(what), count)
                for what, count in report.left_out.items()
            )
        )
    if report.skipped:
        lines.append(_("Not converted:"))
        lines.append("<br>".join("&bull; " + html.escape(s) for s in report.skipped))
    return "<br><br>".join(lines)


def _run(browser, title: str, question: str, work, target: str) -> None:
    from anki.errors import AbortSchemaModification
    from aqt.gui_hooks import operation_did_execute
    from aqt.operations import QueryOp

    if not askUser(question, parent=browser, title=title, defaultno=True):
        return
    try:
        # The review history is moved with SQL, which needs a full sync to
        # reach other devices. The question above already said so.
        mw.col.mod_schema(check=False)
    except AbortSchemaModification:
        return

    def op(col):
        mw.create_backup_now()
        return work(col)

    def on_success(report: convert.Report) -> None:
        mediacleanup.schedule(report.unused_media)
        operation_did_execute(_changes(), None)
        try:
            browser.search()
        except Exception as e:
            logger.debug("could not refresh the browser: %s", e)
        showInfo(
            _report_text(report, target), parent=browser, title=title, textFormat="rich"
        )

    def on_failure(error: Exception) -> None:
        logger.error("conversion failed: %s", error)
        operation_did_execute(_changes(), None)
        showWarning(
            _(
                "The conversion stopped with an error:<br><br><i>{error}</i><br><br>"
                "A backup was made before it started. Notes converted until then "
                "are kept."
            ).format(error=html.escape(str(error))),
            parent=browser,
            title=title,
            textFormat="rich",
        )

    def start() -> None:
        # The notes about to be replaced may be open in the browser's editor,
        # which would otherwise try to save a note that no longer exists.
        editor = getattr(browser, "editor", None)
        if editor is not None:
            editor.set_note(None)
        QueryOp(parent=browser, op=op, success=on_success).failure(
            on_failure
        ).with_progress(_("Converting notes...")).run_in_background()

    editor = getattr(browser, "editor", None)
    if editor is not None and hasattr(editor, "call_after_note_saved"):
        # save any change made in the editor first
        editor.call_after_note_saved(start)
    else:
        start()


_CONVERSION_NOTE = _(
    "Scheduling and review history move to the new cards, and the original "
    "notes are deleted. Anki makes a backup first.<br><br>"
    "This cannot be undone from the Edit menu, and your next sync will have to "
    "upload the whole collection."
)


def on_convert_to_native(browser) -> None:
    nids = browser.selected_notes()
    settings = convert.Settings(getColConfig())
    sets = convert.ioe_sets(mw.col, nids, settings)
    notes = sum(len(s) for s in sets.values())
    if not notes:
        showInfo(
            _("None of the selected notes are Image Occlusion Enhanced notes."),
            parent=browser,
        )
        return
    question = (
        _(
            "Convert {images} image(s) with {notes} note(s) to Anki's built-in "
            "Image Occlusion?<br><br>"
            "Each image becomes one note with a card for every mask. Notes of the "
            "same images are converted too, even if they were not selected."
            "<br><br>"
        ).format(images=len(sets), notes=notes)
        + _CONVERSION_NOTE
    )
    _run(
        browser,
        _("Convert to Anki's Image Occlusion"),
        question,
        lambda col: convert.ioe_to_native(col, nids, settings, paint_annotations),
        _("Anki's Image Occlusion"),
    )


def on_convert_to_ioe(browser) -> None:
    nids = browser.selected_notes()
    native_nids = [
        nid
        for nid in nids
        if convert.is_native_notetype(mw.col.get_note(nid).note_type())
    ]
    if not native_nids:
        showInfo(
            _("None of the selected notes use Anki's built-in Image Occlusion."),
            parent=browser,
        )
        return
    getOrCreateModel()
    settings = convert.Settings(getColConfig())
    question = (
        _(
            "Convert {notes} note(s) of Anki's built-in Image Occlusion to Image "
            "Occlusion Enhanced?<br><br>"
            "Each card becomes a note of its own, as if the image had been "
            "occluded in this add-on.<br><br>"
        ).format(notes=len(native_nids))
        + _CONVERSION_NOTE
    )
    _run(
        browser,
        _("Convert to Image Occlusion Enhanced"),
        question,
        lambda col: convert.native_to_ioe(col, native_nids, settings),
        _("Image Occlusion Enhanced"),
    )


def on_browser_menus_did_init(browser) -> None:
    if mw.col is None or not convert.supports_native(mw.col):
        return
    menu = QMenu(_("Image Occlusion"), browser)
    to_native = QAction(_("Convert to Anki's Image Occlusion..."), browser)
    qconnect(to_native.triggered, lambda: on_convert_to_native(browser))
    to_ioe = QAction(_("Convert to Image Occlusion Enhanced..."), browser)
    qconnect(to_ioe.triggered, lambda: on_convert_to_ioe(browser))
    menu.addAction(to_native)
    menu.addAction(to_ioe)
    browser.form.menu_Notes.addSeparator()
    browser.form.menu_Notes.addMenu(menu)
    # keep a reference so the menu is not garbage collected
    browser._io_convert_menu = menu


def setup_browser_menu() -> None:
    from aqt.gui_hooks import browser_menus_did_init

    browser_menus_did_init.append(on_browser_menus_did_init)
