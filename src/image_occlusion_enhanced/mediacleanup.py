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
Moves mask files that are no longer used to Anki's media trash.

Editing masks writes new files rather than overwriting the old ones, and
converting notes leaves their mask files behind. Both the old and the new
files are noted, and those no note uses are trashed when the profile
closes: until then Edit > Undo can still switch notes back and forth
between them, while Anki starts every session with an empty undo history.
A file some note still uses is never trashed. Files in the trash can be
brought back with Tools > Check Media > Restore Deleted.
"""

import html
import re
from typing import Iterable, List, Set

from .logger import logger

PROFILE_KEY = "imgocc_unused_media"


def schedule(names: Iterable[str]) -> None:
    """Trash these media files when the profile closes, if unused by then"""
    from aqt import mw

    if mw.pm.profile is None:
        return
    pending: List[str] = list(mw.pm.profile.get(PROFILE_KEY) or [])
    for name in names:
        if name and name not in pending:
            pending.append(name)
    mw.pm.profile[PROFILE_KEY] = pending


_SRC_RE = re.compile(r"""\bsrc=(["'])(.*?)\1""", re.I | re.S)


def used_names(col) -> Set[str]:
    """Names of the mask files any note refers to, in one pass over the notes"""
    used: Set[str] = set()
    for (fields,) in col.db.execute("select flds from notes where flds like '%.svg%'"):
        for match in _SRC_RE.finditer(fields):
            used.add(html.unescape(match.group(2)))
    return used


def trash_unused(col, names: Iterable[str]) -> List[str]:
    used = used_names(col)
    unused = [name for name in names if name not in used and col.media.have(name)]
    if unused:
        col.media.trash_files(unused)
    return unused


def on_profile_will_close() -> None:
    from aqt import mw

    if mw.pm.profile is None or mw.col is None:
        return
    pending = mw.pm.profile.get(PROFILE_KEY)
    if not pending:
        return
    try:
        trashed = trash_unused(mw.col, pending)
        logger.debug("trashed %d unused mask files", len(trashed))
    except Exception as e:
        # Nothing is lost by trying again next time
        logger.warning("could not trash unused mask files: %s", e)
        return
    mw.pm.profile[PROFILE_KEY] = []


def setup_media_cleanup() -> None:
    from aqt.gui_hooks import profile_will_close

    profile_will_close.append(on_profile_will_close)
