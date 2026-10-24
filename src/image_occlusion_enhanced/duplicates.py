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
Notices other copies of Image Occlusion Enhanced that are enabled at the
same time, such as the original 2022 release from AnkiWeb or a package
installed from GitHub. Two copies add every button and menu entry twice
and get in each other's way.

Every copy runs this check, so they must agree on which one stays: the
newest version, then a copy from AnkiWeb (it updates itself), then the
folder name. Only that copy offers to disable the others.
"""

import html
import os
import re
from typing import List, Optional, Sequence, Tuple

# Folders Image Occlusion Enhanced is known to be installed in
KNOWN_FOLDERS = ("1374772155", "image_occlusion_enhanced", "image_occlusion_enhanced_2")

PROFILE_KEY = "imgocc_ignored_copies"

Copy = Tuple[str, str, Tuple[int, ...]]  # folder, name, version


def parse_version(text: str) -> Tuple[int, ...]:
    match = re.search(r"""__version__\s*=\s*["']v?([0-9][0-9.]*)""", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).strip(".").split(".") if part)


def is_copy(folder: str, name: str) -> bool:
    return folder in KNOWN_FOLDERS or "image occlusion enhanced" in name.lower()


def keeper(copies: Sequence[Copy]) -> str:
    """The folder of the copy that should stay enabled"""

    def rank(copy: Copy):
        folder, _name, version = copy
        return (version, folder.isdigit(), [-ord(c) for c in folder])

    return max(copies, key=rank)[0]


def to_disable(own: Copy, others: Sequence[Copy]) -> List[Copy]:
    """The copies this one should offer to disable: all others, but only if
    this is the copy that stays."""
    if not others or keeper([own, *others]) != own[0]:
        return []
    return list(others)


# In Anki -----------------------------------------------------------------------


def _version_in(folder_path: str) -> Tuple[int, ...]:
    try:
        with open(os.path.join(folder_path, "_version.py"), encoding="utf-8") as f:
            return parse_version(f.read())
    except OSError:
        return ()


def _own_copy(manager) -> Optional[Copy]:
    from ._version import __version__

    folder = __name__.split(".")[0]
    try:
        name = manager.addon_meta(folder).human_name()
    except Exception:
        name = folder
    return (folder, name, parse_version("__version__ = %r" % __version__))


def check_for_other_copies() -> None:
    from aqt import mw
    from aqt.utils import askUser, showInfo

    from .lang import _

    manager = mw.addonManager
    own = _own_copy(manager)
    if own is None:
        return
    ignored = set(mw.pm.profile.get(PROFILE_KEY) or [])
    others = []
    for meta in manager.all_addon_meta():
        if meta.dir_name == own[0] or not meta.enabled or meta.dir_name in ignored:
            continue
        if is_copy(meta.dir_name, meta.human_name()):
            path = manager.addonsFolder(meta.dir_name)
            others.append((meta.dir_name, meta.human_name(), _version_in(path)))
    disable = to_disable(own, others)
    if not disable:
        return
    names = "".join(
        "<li>%s (%s, folder %s)</li>"
        % (
            html.escape(name),
            "version " + ".".join(map(str, version)) if version else _("older version"),
            html.escape(folder),
        )
        for folder, name, version in disable
    )
    if askUser(
        _(
            "Another copy of Image Occlusion Enhanced is enabled as well:"
            "<ul>{names}</ul>"
            "Running both adds every button twice and can get the editor "
            "into trouble. Disable the other copy? Your notes are not "
            "affected, and it can be turned on again under Tools &gt; Add-ons."
        ).format(names=names),
        title=_("Image Occlusion Enhanced"),
    ):
        for folder, _name, _version in disable:
            manager.toggleEnabled(folder, enable=False)
        showInfo(
            _("Please restart Anki to finish."), title=_("Image Occlusion Enhanced")
        )
    else:
        mw.pm.profile[PROFILE_KEY] = sorted(ignored | {f for f, _n, _v in disable})


def setup_duplicate_check() -> None:
    from aqt import mw
    from aqt.gui_hooks import profile_did_open

    def later() -> None:
        # after Anki's own start-up dialogs
        mw.progress.single_shot(1000, check_for_other_copies)

    profile_did_open.append(later)
