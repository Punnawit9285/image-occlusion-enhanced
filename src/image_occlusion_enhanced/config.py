# -*- coding: utf-8 -*-

# Image Occlusion Enhanced Add-on for Anki
#
# Copyright (C) 2016-2020  Aristotelis P. <https://glutanimate.com/>
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
Sets up configuration, including constants
"""

# TODO: move constants to consts.py

import os
import sys
from copy import deepcopy

from aqt import mw

global IO_FLDS, IO_FLDS_IDS
global IO_MODEL_NAME, IO_CARD_NAME, IO_HOME, IO_HOTKEY

IO_MODEL_NAME = "Image Occlusion Enhanced"
IO_CARD_NAME = "IO Card"

IO_FLDS = {
    "id": "ID (hidden)",
    "hd": "Header",
    "im": "Image",
    "ft": "Footer",
    "rk": "Remarks",
    "sc": "Sources",
    "e1": "Extra 1",
    "e2": "Extra 2",
    "qm": "Question Mask",
    "am": "Answer Mask",
    "om": "Original Mask",
}

IO_FLDS_IDS = ["id", "hd", "im", "qm", "ft", "rk", "sc", "e1", "e2", "am", "om"]

# TODO: Use IDs instead of names to make these compatible with self.ioflds

# fields that aren't user-editable
IO_FIDS_PRIV = ["id", "im", "qm", "am", "om"]

# fields that are synced between an IO Editor session and Anki's Editor
IO_FIDS_PRSV = ["sc"]

# variables for local preference handling
sys_encoding = sys.getfilesystemencoding()
IO_HOME = os.path.expanduser("~")
IO_HOTKEY = "Ctrl+Shift+O"

# default configurations
# TODO: update version number before release
default_conf_local = {"version": 1.25, "dir": IO_HOME, "hotkey": IO_HOTKEY}
default_conf_syncd = {
    "version": 1.25,
    "ofill": "FFEBA2",
    "qfill": "FF7E7E",
    "scol": "2D2D2D",
    "swidth": 3,
    "font": "Arial",
    "fsize": 24,
    "skip": [IO_FLDS["e1"], IO_FLDS["e2"]],
    "flds": IO_FLDS,
}

from . import template


IO_CONF_KEY = "imgocc"


def getColConfig(key=IO_CONF_KEY, default=None):
    """Read a synced config entry.

    Subscripting mw.col.conf still works through a compatibility shim, but it
    prints "conf key imgocc should be fetched with col.get_config()" on every
    single access (issues #147, #261). Note that unlike the old shim this
    returns a *copy*, so changes have to be written back with setColConfig().
    """
    try:
        return mw.col.get_config(key, default=default)
    except AttributeError:  # Anki < 2.1.24
        return mw.col.conf.get(key, default)


def setColConfig(value, key=IO_CONF_KEY):
    """Persist a synced config entry."""
    try:
        mw.col.set_config(key, value)
    except AttributeError:  # Anki < 2.1.24
        mw.col.conf[key] = value
        mw.col.setMod()


def getSyncedConfig():
    # Synced preferences
    conf = getColConfig()

    if conf is None:
        # create initial configuration
        conf = deepcopy(default_conf_syncd)

        # upgrade from IO 2.0:
        old_conf = getColConfig("image_occlusion_conf")
        if old_conf:
            conf["ofill"] = old_conf["initFill[color]"]
            conf["qfill"] = old_conf["mask_fill_color"]
            # insert other upgrade actions here
        setColConfig(conf)

    elif conf["version"] < default_conf_syncd["version"]:
        print("Updating config DB from earlier IO release")
        for key in list(default_conf_syncd.keys()):
            if key not in conf:
                conf[key] = deepcopy(default_conf_syncd[key])
        conf["version"] = default_conf_syncd["version"]
        setColConfig(conf)

    return conf


def getLocalConfig():
    # Local preferences. mw.pm.profile is a plain dict held in memory, so
    # unlike the synced config it can still be mutated in place.
    if "imgocc" not in mw.pm.profile:
        mw.pm.profile["imgocc"] = deepcopy(default_conf_local)
    elif mw.pm.profile["imgocc"].get("version", 0) < default_conf_syncd["version"]:
        for key in list(default_conf_local.keys()):
            if key not in mw.pm.profile["imgocc"]:
                mw.pm.profile["imgocc"][key] = default_conf_local[key]
        mw.pm.profile["imgocc"]["version"] = default_conf_local["version"]

    return mw.pm.profile["imgocc"]


def getOrCreateModel():
    model = mw.col.models.by_name(IO_MODEL_NAME)
    if not model:
        # create model and set up default field name config
        model = template.add_io_model(mw.col)
        conf = getColConfig() or deepcopy(default_conf_syncd)
        conf["flds"] = deepcopy(default_conf_syncd["flds"])
        setColConfig(conf)
        return model
    model_version = getColConfig()["version"]
    if model_version < default_conf_syncd["version"]:
        return template.update_template(mw.col, model_version)
    return model


def getModelConfig():
    model = getOrCreateModel()
    mflds = model["flds"]
    ioflds = getColConfig()["flds"]
    ioflds_priv = []
    for i in IO_FIDS_PRIV:
        ioflds_priv.append(ioflds[i])
    # preserve fields if they are marked as sticky in the IO note type:
    ioflds_prsv = []
    for fld in mflds:
        fname = fld["name"]
        if fld["sticky"] and fname not in ioflds_priv:
            ioflds_prsv.append(fname)

    return model, mflds, ioflds, ioflds_priv, ioflds_prsv


def loadConfig(self):
    """load and/or create add-on preferences"""
    # FIXME: return config dictionary instead of this hacky
    # instantiation of instance variables
    self.sconf_dflt = default_conf_syncd
    self.lconf_dflt = default_conf_local
    self.sconf = getSyncedConfig()
    self.lconf = getLocalConfig()

    (
        self.model,
        self.mflds,
        self.ioflds,
        self.ioflds_priv,
        self.ioflds_prsv,
    ) = getModelConfig()
