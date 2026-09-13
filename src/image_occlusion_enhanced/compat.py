# -*- coding: utf-8 -*-

# Image Occlusion Enhanced Add-on for Anki
#
# Copyright (C) 2016-2022  Aristotelis P. <https://glutanimate.com/>
# Copyright (C) 2012-2015  Tiago Barroso <tmbb@campus.ul.pt>
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
#
# If not, please request a copy through one of the means of contact
# listed here: <https://glutanimate.com/contact/>.
#
# Any modifications to this file must keep this entire header intact.

"""
Version-tolerant access to the Anki APIs this add-on depends on.

Anki renames its Python API over time: camelCase methods such as findNotes
gain snake_case replacements, keep working for a while behind deprecation
shims, and are eventually removed. Calling them directly means the add-on
breaks - often at import time, taking every feature down with it - on the
first release that drops one.

Every function here prefers the current API and falls back to the older one,
so the rest of the add-on never has to know which Anki it is running on.
Nothing in this module may raise at import time.
"""

from typing import Any, Callable, Iterable, Optional, Sequence

import aqt.utils as _aqt_utils
from aqt import mw

from .logger import logger


def _call_first(obj: Any, names: Sequence[str], *args, **kwargs) -> Any:
    """Call the first of ``names`` that exists on ``obj``."""
    for name in names:
        fn = getattr(obj, name, None)
        if fn is not None:
            return fn(*args, **kwargs)
    raise AttributeError(
        "%s provides none of: %s" % (type(obj).__name__, ", ".join(names))
    )


# Notes ----------------------------------------------------------------------


def find_notes(col, query: str) -> Sequence[int]:
    return _call_first(col, ("find_notes", "findNotes"), query)


def get_note(col, note_id: int):
    return _call_first(col, ("get_note", "getNote"), note_id)


def new_note(col, notetype):
    if hasattr(col, "new_note"):
        return col.new_note(notetype)
    from anki.notes import Note

    return Note(col, notetype)


def add_note(col, note, deck_id: int) -> None:
    """Add a note to a specific deck.

    The modern call takes the deck explicitly. Older versions picked it up
    from the note type instead, which is why callers used to set
    ``model["did"]`` before adding - and why cards sometimes landed in the
    wrong deck.
    """
    if hasattr(col, "add_note"):
        col.add_note(note, deck_id)
        return
    _call_first(note, ("note_type", "model"))["did"] = deck_id
    col.addNote(note)


def update_note(col, note) -> None:
    if hasattr(col, "update_note"):
        col.update_note(note)
    else:
        note.flush()


def remove_notes(col, note_ids: Iterable[int]) -> None:
    _call_first(col, ("remove_notes", "remNotes"), list(note_ids))


# Note types -----------------------------------------------------------------


def notetype_by_name(col, name: str):
    return _call_first(col.models, ("by_name", "byName"), name)


def field_names(col, notetype) -> Sequence[str]:
    return _call_first(col.models, ("field_names", "fieldNames"), notetype)


def rename_field(col, notetype, field, new_name: str) -> None:
    _call_first(col.models, ("rename_field", "renameField"), notetype, field, new_name)


def new_notetype(col, name: str):
    return _call_first(col.models, ("new",), name)


def new_field(col, name: str):
    return _call_first(col.models, ("new_field", "newField"), name)


def add_field(col, notetype, field) -> None:
    _call_first(col.models, ("add_field", "addField"), notetype, field)


def new_template(col, name: str):
    return _call_first(col.models, ("new_template", "newTemplate"), name)


def add_template(col, notetype, template) -> None:
    _call_first(col.models, ("add_template", "addTemplate"), notetype, template)


def add_notetype(col, notetype):
    """Save a brand-new note type and return it as stored.

    The modern add_dict() does not write the new id back into the dict it was
    given, and a note type without an id cannot have notes created from it, so
    the saved copy is read back by name rather than trusting the argument.
    """
    if hasattr(col.models, "add_dict"):
        col.models.add_dict(notetype)
    else:
        col.models.add(notetype)
    return notetype_by_name(col, notetype["name"]) or notetype


def save_notetype(col, notetype) -> None:
    if hasattr(col.models, "update_dict"):
        col.models.update_dict(notetype)
    else:
        col.models.save(notetype)


# Undo -----------------------------------------------------------------------


def begin_undo_group(col, label: str) -> Optional[int]:
    """Open a single undo step that the following collection writes join.

    mw.checkpoint() used to provide this, but it has been a no-op for several
    releases ("checkpoints are no longer supported"), so adding a batch of
    occlusion cards could not be undone as one action.
    """
    if hasattr(col, "add_custom_undo_entry"):
        try:
            return col.add_custom_undo_entry(label)
        except Exception as e:
            logger.warning("could not open undo step %r: %s", label, e)
            return None
    checkpoint = getattr(mw, "checkpoint", None)
    if checkpoint is not None:
        checkpoint(label)
    return None


def end_undo_group(col, token: Optional[int]) -> None:
    """Merge everything written since begin_undo_group() into that step."""
    if token is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(token)
        except Exception as e:
            logger.warning("could not merge undo entries: %s", e)
    refresh_undo_menu()


def refresh_undo_menu() -> None:
    fn = getattr(mw, "update_undo_actions", None)
    if fn is None:
        return
    try:
        fn()
    except Exception as e:
        logger.debug("could not refresh undo actions: %s", e)


def refresh_main_window() -> None:
    """Re-render the main window after writing to the collection directly."""
    reset = getattr(mw, "reset", None)
    if reset is not None:
        reset()
    elif hasattr(mw, "moveToState") and getattr(mw, "state", None):
        mw.moveToState(mw.state)
    refresh_undo_menu()


# Widgets --------------------------------------------------------------------


def selected_deck_id(chooser) -> int:
    if hasattr(chooser, "selected_deck_id"):
        return chooser.selected_deck_id
    return chooser.selectedId()


# Hooks ----------------------------------------------------------------------


def add_legacy_hook(name: str, fn: Callable) -> bool:
    """Register on Anki's legacy string-named hook system, if it still exists.

    Only used as a fallback for versions that predate the matching gui_hooks
    entry, so its absence is never an error.
    """
    try:
        from anki.hooks import addHook
    except ImportError:
        return False
    addHook(name, fn)
    return True


def remove_legacy_hook(name: str, fn: Callable) -> None:
    try:
        from anki.hooks import remHook
    except ImportError:
        return
    try:
        remHook(name, fn)
    except Exception:
        pass


def wrap_method(cls: type, name: str, new: Callable, pos: str = "after") -> bool:
    """Monkey-patch ``cls.name`` via anki.hooks.wrap, skipping it if either
    the method or wrap() is gone.

    A patch that cannot be applied is a lost nicety; an AttributeError raised
    while the add-on is loading is a completely broken add-on.
    """
    old = getattr(cls, name, None)
    if old is None:
        logger.warning("%s.%s not found; skipping patch", cls.__name__, name)
        return False
    try:
        from anki.hooks import wrap
    except ImportError:
        logger.warning("anki.hooks.wrap unavailable; skipping %s patch", name)
        return False
    setattr(cls, name, wrap(old, new, pos))
    return True


# aqt.utils helpers ----------------------------------------------------------
#
# Resolved once, by whichever spelling this Anki provides. Import failures here
# would stop the whole add-on from loading, so a missing helper degrades to a
# plain QMessageBox or a no-op instead.


def _resolve(*names: str) -> Optional[Callable]:
    for name in names:
        fn = getattr(_aqt_utils, name, None)
        if fn is not None:
            return fn
    return None


_restore_geom = _resolve("restoreGeom", "restore_geom")
_save_geom = _resolve("saveGeom", "save_geom")
_ask_user = _resolve("askUser", "ask_user")
_show_warning = _resolve("showWarning", "show_warning")
_show_info = _resolve("showInfo", "show_info")


def restoreGeom(widget, key: str, *args, **kwargs) -> None:
    if _restore_geom is not None:
        _restore_geom(widget, key, *args, **kwargs)


def saveGeom(widget, key: str) -> None:
    if _save_geom is not None:
        _save_geom(widget, key)


def _message_box(kind: str, text: str, parent=None, title: str = "Anki"):
    from aqt.qt import QMessageBox

    return getattr(QMessageBox, kind)(parent or mw, title, text)


def askUser(text: str, parent=None, title: str = "Anki", **kwargs) -> bool:
    if _ask_user is not None:
        return _ask_user(text, parent=parent, title=title, **kwargs)
    from aqt.qt import QMessageBox

    return _message_box("question", text, parent, title) == (
        QMessageBox.StandardButton.Yes
    )


def showWarning(text: str, *args, **kwargs):
    if _show_warning is not None:
        return _show_warning(text, *args, **kwargs)
    return _message_box("warning", text, kwargs.get("parent"))


def showInfo(text: str, *args, **kwargs):
    if _show_info is not None:
        return _show_info(text, *args, **kwargs)
    return _message_box("information", text, kwargs.get("parent"))
