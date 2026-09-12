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
Shared design tokens and Qt styling for the Image Occlusion dialogs.

The token tables below are the single source of truth for the add-on's look.
The Qt side consumes them through qtStylesheet(); the SVG-Edit side mirrors
the same values as CSS custom properties in svg-edit/editor/io-theme.css.
Keep the two in sync when changing a colour.
"""

from typing import Dict

LIGHT = "light"
DARK = "dark"

TOKENS: Dict[str, Dict[str, str]] = {
    LIGHT: {
        "bg": "#f4f5f7",
        "surface": "#ffffff",
        "surface_raised": "#ffffff",
        "surface_sunken": "#eaecef",
        "border": "#d6d9e0",
        "border_strong": "#b6bbc4",
        "text": "#1f2329",
        "text_muted": "#6b7280",
        "accent": "#2f6feb",
        "accent_hover": "#2a62d0",
        "accent_text": "#ffffff",
        "danger": "#d93025",
        "shadow": "rgba(16, 20, 28, 0.10)",
    },
    DARK: {
        "bg": "#1e1f22",
        "surface": "#26282c",
        "surface_raised": "#303236",
        "surface_sunken": "#191a1d",
        "border": "#3a3d43",
        "border_strong": "#52565e",
        "text": "#e5e7ea",
        "text_muted": "#9aa0a8",
        "accent": "#4c8dff",
        "accent_hover": "#6ba0ff",
        "accent_text": "#10131a",
        "danger": "#f2685f",
        "shadow": "rgba(0, 0, 0, 0.45)",
    },
}


def isNightMode() -> bool:
    """Whether Anki is currently in dark mode.

    Falls back to light mode on Anki builds that do not expose theme_manager,
    so that the add-on keeps loading rather than failing at import time.
    """
    try:
        from aqt.theme import theme_manager

        return bool(theme_manager.night_mode)
    except Exception:  # pragma: no cover - depends on Anki version
        return False


def themeName(night: bool) -> str:
    """Token table key for the given mode."""
    return DARK if night else LIGHT


def tokens(night: bool) -> Dict[str, str]:
    """Token table for the given mode."""
    return TOKENS[themeName(night)]


def qtStylesheet(night: bool) -> str:
    """Build the QSS applied to the Image Occlusion dialogs.

    Applied once per dialog; Qt cascades it to every child widget. Widgets that
    need to opt out of a rule carry a dynamic property (e.g. ioPrimary) which is
    matched by the selectors below.
    """
    t = tokens(night)
    return _QSS_TEMPLATE.format(**t)


# Note on QSS: attribute selectors match Qt *dynamic properties*, so any widget
# whose property changes after polish needs style().unpolish()/polish() to pick
# the new rule up. See ImgOccEdit._setPrimaryButton().

_QSS_TEMPLATE = """
QDialog {{
    background: {bg};
}}
QWidget {{
    color: {text};
}}
QLabel {{
    color: {text};
    background: transparent;
}}
QLabel[ioMuted="true"] {{
    color: {text_muted};
}}
QLabel[ioHeading="true"] {{
    color: {text};
    font-weight: 600;
}}

/* --- Tabs --------------------------------------------------------------- */
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 8px;
    background: {surface};
    top: -1px;
}}
QTabBar {{
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: transparent;
    color: {text_muted};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 16px;
    margin: 2px 2px 6px 2px;
    font-weight: 500;
}}
QTabBar::tab:hover {{
    color: {text};
    background: {surface_sunken};
}}
QTabBar::tab:selected {{
    color: {accent_text};
    background: {accent};
}}

/* --- Text entry --------------------------------------------------------- */
QPlainTextEdit, QTextEdit, QLineEdit {{
    background: {surface_sunken};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {{
    border: 1px solid {accent};
}}

/* --- Buttons ------------------------------------------------------------ */
QPushButton {{
    background: {surface_raised};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 18px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: {surface_sunken};
}}
QPushButton:pressed {{
    background: {surface_sunken};
    border-color: {accent};
}}
QPushButton:disabled {{
    color: {text_muted};
    border-color: {border};
}}
QPushButton[ioPrimary="true"] {{
    background: {accent};
    color: {accent_text};
    border: 1px solid {accent};
}}
QPushButton[ioPrimary="true"]:hover {{
    background: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton[ioIcon="true"] {{
    padding: 6px 10px;
    font-weight: 600;
}}

/* --- Combo / spin ------------------------------------------------------- */
QComboBox, QSpinBox, QFontComboBox {{
    background: {surface_raised};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 18px;
}}
QComboBox:focus, QSpinBox:focus, QFontComboBox:focus {{
    border-color: {accent};
}}
QComboBox::drop-down, QFontComboBox::drop-down {{
    border: none;
    width: 18px;
}}
/* Reserve room for the native spin arrows; the padding above squeezes them
   down to slivers otherwise. Arrows themselves are left unstyled so they keep
   the platform look. */
QSpinBox {{
    padding-right: 2px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background: {surface_raised};
    color: {text};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: {accent_text};
    outline: none;
}}

/* --- Scroll areas ------------------------------------------------------- */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border_strong};
    border-radius: 6px;
    min-height: 28px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {text_muted};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {border_strong};
    border-radius: 6px;
    min-width: 28px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {text_muted};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* --- Misc --------------------------------------------------------------- */
QFrame[ioSeparator="true"] {{
    background: {border};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QWidget#ioBottomBar {{
    background: {bg};
}}
QToolTip {{
    background: {surface_raised};
    color: {text};
    border: 1px solid {border};
    padding: 4px 6px;
}}
"""
