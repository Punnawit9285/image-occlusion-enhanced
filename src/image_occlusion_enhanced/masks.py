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
Turns the masks drawn in the editor into the question and answer masks of
each card.

Plain Python without Anki imports, so that it can be unit tested.
"""

import re
import uuid
from typing import List, Optional, Sequence
from xml.dom import minidom

# Occlusion modes. The two-letter codes are the middle part of every note ID
# ("<uuid>-<mode>-<number>") and of the mask file names, so they must never
# change.
HIDE_ALL_GUESS_ONE = "ao"
HIDE_ONE_GUESS_ONE = "oa"
HIDE_ALL_GUESS_ALL = "ag"
# "Hide All, Reveal All" from IO 2.x, one card per mask. Its notes can still
# be reviewed; editing them converts them to HIDE_ALL_GUESS_ONE.
LEGACY_HIDE_ALL_REVEAL_ALL = "aa"

MODES = (HIDE_ALL_GUESS_ONE, HIDE_ONE_GUESS_ONE, HIDE_ALL_GUESS_ALL)

# Hide All, Guess All makes a single note for the whole image. Its note ID
# ends in this number; the masks themselves are still numbered from 1.
WHOLE_IMAGE_NOTE_NR = 0

# A note ID, also used as the id of the mask it was generated from.
NOTE_ID_RE = re.compile(r"^(?P<uniq>.+)-(?P<mode>ao|oa|aa|ag)-(?P<nr>\d+)$")


def new_revision() -> str:
    """A short code that sets mask files written at one time apart from
    earlier versions of the same masks."""
    return uuid.uuid4().hex[:6]


def mask_file_name(base_id: str, revision: str, kind: str) -> str:
    """Name of a mask file in the media folder.

    base_id is a note ID for the question ("Q") and answer ("A") masks of a
    card, or the occlusion ID ("<uuid>-<mode>") for files that every note of
    an image shares: the original mask ("O") and the common answer mask of
    Hide One, Guess One.

    Every save gets a new revision, so an edited mask never reuses the name
    of the version before it. Overwriting a file under the same name is what
    made Anki's web views keep showing the old masks after an edit.
    """
    # Recent Anki versions lower-case the names of new media files; doing it
    # here keeps the names the same on every version.
    return ("%s-%s-%s.svg" % (base_id, revision, kind)).lower()


def layer_nodes(svg_node) -> list:
    """Layer nodes (the topmost group nodes below the SVG node)"""
    assert svg_node.nodeType == svg_node.ELEMENT_NODE
    assert svg_node.nodeName == "svg"
    nodes = [node for node in svg_node.childNodes if node.nodeType == node.ELEMENT_NODE]
    assert len(nodes) >= 1
    # last, i.e. top-most element, needs to be a layer:
    assert nodes[-1].nodeName == "g"
    return nodes


def mask_layer(svg_node):
    """The topmost layer, which holds the masks"""
    return layer_nodes(svg_node)[-1]


def set_question_attribs(node, qfill: str) -> None:
    """Set question node color and class"""
    if node.nodeType == node.ELEMENT_NODE and node.tagName != "text":
        node.setAttribute("class", "qshape")
        if node.hasAttribute("fill"):
            node.setAttribute("fill", qfill)
        for child in node.childNodes:
            set_question_attribs(child, qfill)


def build_mask(
    svg: str,
    mode: str,
    side: str,
    mask_indexes: Sequence[int],
    target: Optional[int],
    qfill: str,
) -> str:
    """The question ("Q") or answer ("A") mask of one card.

    mask_indexes are the positions of the mask elements among the child
    nodes of the mask layer, and target is the one the card asks about. Hide
    All, Guess All asks about every mask, so it takes no target.
    """
    svg_node = minidom.parseString(svg.encode("utf-8")).documentElement
    mlayer = mask_layer(svg_node)
    if mode == HIDE_ONE_GUESS_ONE:
        # Q: only the asked mask. A: no masks.
        for i in reversed(mask_indexes):
            node = mlayer.childNodes[i]
            if i == target and side == "Q":
                set_question_attribs(node, qfill)
                node.setAttribute("class", "qshape")
            else:
                mlayer.removeChild(node)
    elif mode == HIDE_ALL_GUESS_ALL:
        # Q: every mask, each one asked. A: no masks.
        for i in reversed(mask_indexes):
            node = mlayer.childNodes[i]
            if side == "Q":
                set_question_attribs(node, qfill)
            else:
                mlayer.removeChild(node)
    else:
        # Hide All, Guess One. Q: all masks, the asked one highlighted.
        # A: all masks but the asked one.
        node = mlayer.childNodes[target]
        if side == "Q":
            set_question_attribs(node, qfill)
        else:
            mlayer.removeChild(node)
    return svg_node.toxml()


def mask_ids(svg: str) -> List[str]:
    """IDs of the masks in a mask file, in drawing order"""
    svg_node = minidom.parseString(svg.encode("utf-8")).documentElement
    ids = []
    for node in mask_layer(svg_node).childNodes:
        if node.nodeType != node.ELEMENT_NODE or node.nodeName == "title":
            continue
        if node.hasAttribute("id") and NOTE_ID_RE.match(node.getAttribute("id")):
            ids.append(node.getAttribute("id"))
    return ids
