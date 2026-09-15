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
Image Occlusion editor dialog
"""

import html
import os
import uuid
from typing import List, Optional

from anki.config import Config
from aqt import deckchooser, mw, tagedit, webview
from aqt.qt import (
    QApplication,
    QBrush,
    QBuffer,
    QColor,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFont,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QIcon,
    QImage,
    QIODevice,
    QKeySequence,
    QLabel,
    QMenu,
    QMovie,
    QPainter,
    QPixmap,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSize,
    Qt,
    QTabWidget,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextEdit,
    QTextFormat,
    QTextImageFormat,
    QToolButton,
    QUrl,
    QVBoxLayout,
    QWidget,
    sip,
    pyqtSignal,
)
from aqt.utils import tooltip

from .compat import (
    add_legacy_hook,
    askUser,
    remove_legacy_hook,
    restoreGeom,
    saveGeom,
)
from .config import *
from .consts import *
from .dialogs import ioHelp
from .lang import _
from .logger import logger
from .theme import isNightMode, qtStylesheet
from .utils import path_to_img_element


class ImgOccWebPage(webview.AnkiWebPage):
    def acceptNavigationRequest(self, url, navType, isMainFrame):
        return True


class ImgOccWebView(webview.AnkiWebView):

    escape_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._domDone = False
        # Used only when this Anki's web view no longer exposes the private
        # _queueAction/_pendingActions queue we normally borrow (issue #316).
        self._io_pending = []

    def _onBridgeCmd(self, cmd):
        # ignore webchannel messages that arrive after underlying webview
        # deleted
        if sip.isdeleted(self):
            return

        if cmd == "domDone":
            return

        if cmd == "svgEditDone":
            self._domDone = True
            self._maybeRunActions()
        else:
            return self.onBridgeCmd(cmd)

    def runOnLoaded(self, callback):
        self._domDone = False
        if hasattr(self, "_queueAction") and hasattr(self, "_pendingActions"):
            self._queueAction("callback", callback)
        else:
            self._io_pending.append(callback)

    def _maybeRunActions(self):
        # Anki's own queue, when it still has one. Everything queued on this
        # view - including Anki's evals - is held back until SVG-Edit reports
        # ready, because svgCanvas does not exist before that.
        pending = getattr(self, "_pendingActions", None)
        while pending and self._domDone:
            name, args = pending.pop(0)

            if name == "eval":
                self._runJs(*args)
            elif name == "setHtml":
                set_html = getattr(self, "_setHtml", None)
                if set_html is not None:
                    set_html(*args)
                else:
                    from aqt.qt import QWebEngineView

                    QWebEngineView.setHtml(self, *args)
            elif name == "callback":
                callback = args[0]
                callback()
            else:
                raise Exception(
                    _("unknown action: {action_name}").format(action_name=name)
                )

        while self._io_pending and self._domDone:
            self._io_pending.pop(0)()

    def _runJs(self, js, callback=None):
        """Run JS immediately, bypassing Anki's queue.

        The public evalWithCallback() would re-enqueue onto the very queue
        being drained here and loop forever, so fall back to the raw Qt call.
        """
        eval_now = getattr(self, "_evalWithCallback", None)
        if eval_now is not None:
            eval_now(js, callback)
        elif callback is not None:
            self.page().runJavaScript(js, callback)
        else:
            self.page().runJavaScript(js)

    def onEsc(self):
        self.escape_pressed.emit()


def _enumValue(value):
    """Plain int for a Qt enum member, across PyQt enum flavours."""
    return getattr(value, "value", value)


_FOREGROUND = _enumValue(QTextFormat.Property.ForegroundBrush)
_BACKGROUND = _enumValue(QTextFormat.Property.BackgroundBrush)
# Marks an image whose size was reduced for display only, so the serialiser
# knows not to write that size into the note.
_DISPLAY_SCALED = _enumValue(QTextFormat.Property.UserProperty) + 1

_SUPERSCRIPT = QTextCharFormat.VerticalAlignment.AlignSuperScript
_SUBSCRIPT = QTextCharFormat.VerticalAlignment.AlignSubScript
_NORMAL_ALIGNMENT = QTextCharFormat.VerticalAlignment.AlignNormal

# Images accepted into fields. Broader than the formats usable as an occlusion
# background, since these only have to display on the card.
FIELD_IMAGE_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "tif", "tiff",
}


def _isChromatic(color) -> bool:
    """Whether a pasted colour is worth keeping.

    Web pages and word processors set black text and white backgrounds
    explicitly, and keeping those would litter the field with spans that force
    black text on the card. Only colours with actual hue survive a paste; the
    toolbar can still apply any colour deliberately.
    """
    return color.isValid() and color.alpha() > 0 and color.saturation() >= 30


class IOFieldEdit(QTextEdit):
    """Rich text field entry: formatting, plus pasted and dropped images.

    Anki stores field content as HTML. Formatting is written back as a small,
    predictable set of tags (b, i, u, s, sup, sub, a, and spans for colours),
    and images live in the collection's media folder, referenced as
    <img src="filename"> and shown inline while editing (issues #276, #310).

    The document's base URL is the media folder, so a bare filename in an
    img src resolves both when loading a note and when serialising back out.
    """

    # Emitted with the field itself, so one toolbar can serve every field.
    focused = pyqtSignal(object)
    formatChanged = pyqtSignal(object)

    # Images wider than this are scaled down for display only; the stored
    # markup is untouched, so cards still get the full-resolution file.
    MAX_DISPLAY_WIDTH = 320

    def __init__(self, parent=None):
        QTextEdit.__init__(self, parent)
        # Pastes are cleaned by insertFromMimeData() rather than accepted
        # wholesale, so Qt's own rich text import stays off.
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setAcceptDrops(True)
        self._original = ""
        self.currentCharFormatChanged.connect(
            lambda _fmt: self.formatChanged.emit(self)
        )
        try:
            self.document().setBaseUrl(
                QUrl.fromLocalFile(os.path.join(mw.col.media.dir(), ""))
            )
        except Exception:
            # No collection open yet; images simply will not preview.
            pass

    def focusInEvent(self, event) -> None:
        QTextEdit.focusInEvent(self, event)
        self.focused.emit(self)

    def keyPressEvent(self, event) -> None:
        for key, action in (
            (QKeySequence.StandardKey.Bold, self.toggleBold),
            (QKeySequence.StandardKey.Italic, self.toggleItalic),
            (QKeySequence.StandardKey.Underline, self.toggleUnderline),
        ):
            if event.matches(key):
                action()
                event.accept()
                return
        QTextEdit.keyPressEvent(self, event)

    # -- content round-tripping

    def setFieldHtml(self, text: str) -> None:
        """Load a field's stored HTML, remembering it for preservation."""
        self._original = text or ""
        self.setHtml(self._original)
        self._fitImagesForDisplay()
        self.document().setModified(False)

    def fieldHtml(self) -> str:
        """Serialise back to the HTML the note type expects.

        If nothing was touched the stored value is returned verbatim. Field
        content can contain arbitrary markup produced by Anki's own editor -
        the Sources field is shared with it - and re-serialising that through a
        QTextDocument would quietly rewrite it.
        """
        if not self.document().isModified():
            return self._original
        return self._serialize()

    def _serialize(self) -> str:
        doc = self.document()
        parts: List[str] = []
        block = doc.begin()
        first_block = True
        while block.isValid():
            if not first_block:
                parts.append("<br />")
            first_block = False
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    parts.append(self._serializeFragment(fragment))
                it += 1
            block = block.next()
        return "".join(parts)

    def _serializeFragment(self, fragment) -> str:
        fmt = fragment.charFormat()
        if fmt.isImageFormat():
            return self._serializeImage(fmt.toImageFormat())
        text = html.escape(fragment.text(), quote=False)
        if not text:
            return ""
        # Qt keeps a <br> inside a loaded paragraph, and a Shift+Enter, as a
        # line separator character within the block rather than as a new
        # block. Without this, editing a field that had line breaks would
        # silently run its lines together.
        text = text.replace(" ", "<br />").replace(" ", "<br />")

        alignment = fmt.verticalAlignment()
        if alignment == _SUPERSCRIPT:
            text = "<sup>%s</sup>" % text
        elif alignment == _SUBSCRIPT:
            text = "<sub>%s</sub>" % text
        # Qt draws links underlined and in the palette's link colour, and records
        # both on the text itself. Writing them back would bake editor styling -
        # a dark-mode UI colour included - into the note on every save, so a
        # link's look is left to the card. Its target is kept below.
        is_link = fmt.isAnchor() and bool(fmt.anchorHref())
        if fmt.fontStrikeOut():
            text = "<s>%s</s>" % text
        if fmt.fontUnderline() and not is_link:
            text = "<u>%s</u>" % text
        if fmt.fontItalic():
            text = "<i>%s</i>" % text
        if fmt.fontWeight() > 500:
            text = "<b>%s</b>" % text

        styles = []
        if fmt.hasProperty(_FOREGROUND) and not is_link:
            styles.append("color: %s" % fmt.foreground().color().name())
        if fmt.hasProperty(_BACKGROUND):
            styles.append("background-color: %s" % fmt.background().color().name())
        if styles:
            text = '<span style="%s;">%s</span>' % ("; ".join(styles), text)

        if fmt.isAnchor() and fmt.anchorHref():
            text = '<a href="%s">%s</a>' % (html.escape(fmt.anchorHref()), text)
        return text

    def _serializeImage(self, image_format) -> str:
        name = image_format.name()
        if not name:
            return ""
        if image_format.boolProperty(_DISPLAY_SCALED) or image_format.width() <= 0:
            return path_to_img_element(name)
        # A width that came from the note itself, e.g. set in Anki's editor.
        return '<img src="%s" width="%d" />' % (
            os.path.split(name)[1],
            round(image_format.width()),
        )

    def _fitImagesForDisplay(self) -> None:
        """Shrink large images loaded from a note, for display only."""
        try:
            media_dir = mw.col.media.dir()
        except Exception:
            return
        doc = self.document()
        pending = []
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    image_format = fragment.charFormat().toImageFormat()
                    if image_format.width() <= 0:
                        pending.append(
                            (fragment.position(), fragment.length(), image_format)
                        )
                it += 1
            block = block.next()
        # Applied after the walk: changing formats can split fragments, which
        # would invalidate the iterator mid-loop.
        for position, length, image_format in pending:
            image = QImage(os.path.join(media_dir, image_format.name()))
            if image.isNull() or image.width() <= self.MAX_DISPLAY_WIDTH:
                continue
            self._scaleForDisplay(image_format, image)
            cursor = QTextCursor(doc)
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(image_format)

    def _scaleForDisplay(self, image_format, image) -> None:
        scale = self.MAX_DISPLAY_WIDTH / float(image.width())
        image_format.setWidth(self.MAX_DISPLAY_WIDTH)
        image_format.setHeight(image.height() * scale)
        image_format.setProperty(_DISPLAY_SCALED, True)

    # -- formatting

    def _editFormats(self, edit) -> None:
        """Apply ``edit`` to the selected text, or to what gets typed next.

        ``edit`` receives a QTextCharFormat and may change it in place or return
        a replacement. Images inside a selection are left alone.
        """
        cursor = self.textCursor()
        if not cursor.hasSelection():
            fmt = self.currentCharFormat()
            replacement = edit(fmt)
            self.setCurrentCharFormat(replacement if replacement is not None else fmt)
            return

        doc = self.document()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        ranges = []
        block = doc.findBlock(start)
        while block.isValid() and block.position() < end:
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    a = max(fragment.position(), start)
                    b = min(fragment.position() + fragment.length(), end)
                    fmt = fragment.charFormat()
                    if a < b and not fmt.isImageFormat():
                        ranges.append((a, b, QTextCharFormat(fmt)))
                it += 1
            block = block.next()

        editor = QTextCursor(doc)
        editor.beginEditBlock()
        for a, b, fmt in ranges:
            replacement = edit(fmt)
            editor.setPosition(a)
            editor.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
            editor.setCharFormat(replacement if replacement is not None else fmt)
        editor.endEditBlock()
        # Re-apply the original selection so toolbar state tracks it.
        self.setTextCursor(cursor)

    def toggleBold(self) -> None:
        on = self.currentCharFormat().fontWeight() > 500
        self._editFormats(lambda f: f.setFontWeight(400 if on else 700))

    def toggleItalic(self) -> None:
        on = self.currentCharFormat().fontItalic()
        self._editFormats(lambda f: f.setFontItalic(not on))

    def toggleUnderline(self) -> None:
        on = self.currentCharFormat().fontUnderline()
        self._editFormats(lambda f: f.setFontUnderline(not on))

    def toggleStrikeOut(self) -> None:
        on = self.currentCharFormat().fontStrikeOut()
        self._editFormats(lambda f: f.setFontStrikeOut(not on))

    def toggleVerticalAlignment(self, alignment) -> None:
        on = self.currentCharFormat().verticalAlignment() == alignment
        self._editFormats(
            lambda f: f.setVerticalAlignment(_NORMAL_ALIGNMENT if on else alignment)
        )

    def applyTextColor(self, color) -> None:
        """Colour the text; None returns it to the default colour."""

        def edit(fmt):
            if color is None:
                fmt.clearForeground()
            else:
                fmt.setForeground(QBrush(color))

        self._editFormats(edit)

    def applyHighlight(self, color) -> None:
        """Highlight behind the text; None removes it."""

        def edit(fmt):
            if color is None:
                fmt.clearBackground()
            else:
                fmt.setBackground(QBrush(color))

        self._editFormats(edit)

    def clearFormatting(self) -> None:
        self._editFormats(lambda f: QTextCharFormat())

    # -- pasting and dropping

    def canInsertFromMimeData(self, source) -> bool:
        if source.hasImage() or self._imagePaths(source) or source.hasHtml():
            return True
        return QTextEdit.canInsertFromMimeData(self, source)

    def insertFromMimeData(self, source) -> None:
        if self._insertImages(source):
            return
        if source.hasHtml():
            self._insertCleanHtml(source.html())
            return
        self.insertPlainText(source.text())

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasImage() or self._imagePaths(event.mimeData()):
            event.acceptProposedAction()
            return
        QTextEdit.dragEnterEvent(self, event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasImage() or self._imagePaths(event.mimeData()):
            event.acceptProposedAction()
            return
        QTextEdit.dragMoveEvent(self, event)

    def dropEvent(self, event) -> None:
        if self._insertImages(event.mimeData()):
            event.acceptProposedAction()
            return
        QTextEdit.dropEvent(self, event)

    def _insertCleanHtml(self, markup: str) -> None:
        """Paste rich text keeping only the formatting the field can store.

        Fonts and sizes from the source are dropped on purpose: they would show
        while editing but vanish on save, since the serialiser does not write
        them.
        """
        source = QTextDocument()
        source.setHtml(markup)
        cursor = self.textCursor()
        cursor.beginEditBlock()
        block = source.begin()
        first_block = True
        while block.isValid():
            if not first_block:
                cursor.insertBlock()
            first_block = False
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid() and not fragment.charFormat().isImageFormat():
                    cursor.insertText(
                        fragment.text(), self._cleanFormat(fragment.charFormat())
                    )
                it += 1
            block = block.next()
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    @staticmethod
    def _cleanFormat(source) -> QTextCharFormat:
        fmt = QTextCharFormat()
        if source.fontWeight() > 500:
            fmt.setFontWeight(700)
        if source.fontItalic():
            fmt.setFontItalic(True)
        if source.fontUnderline():
            fmt.setFontUnderline(True)
        if source.fontStrikeOut():
            fmt.setFontStrikeOut(True)
        if source.verticalAlignment() in (_SUPERSCRIPT, _SUBSCRIPT):
            fmt.setVerticalAlignment(source.verticalAlignment())
        foreground = source.foreground().color()
        if source.hasProperty(_FOREGROUND) and _isChromatic(foreground):
            fmt.setForeground(source.foreground())
        background = source.background().color()
        if source.hasProperty(_BACKGROUND) and _isChromatic(background):
            fmt.setBackground(source.background())
        if source.isAnchor() and source.anchorHref():
            fmt.setAnchor(True)
            fmt.setAnchorHref(source.anchorHref())
            # Same reasoning as in _serializeFragment: keep where a pasted
            # link points, not how the source page painted it.
            fmt.setFontUnderline(False)
            fmt.clearForeground()
        return fmt

    @staticmethod
    def _visibleText(source) -> str:
        if source.hasHtml():
            doc = QTextDocument()
            doc.setHtml(source.html())
            text = doc.toPlainText()
        else:
            text = source.text() if source.hasText() else ""
        return text.replace("￼", "").strip()

    def _imagePaths(self, source) -> List[str]:
        """Local image files carried by a drop or paste."""
        paths = []
        if not source.hasUrls():
            return paths
        for url in source.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            if ext in FIELD_IMAGE_EXTENSIONS and os.path.isfile(path):
                paths.append(path)
        return paths

    def _insertImages(self, source) -> bool:
        paths = self._imagePaths(source)
        if paths:
            for path in paths:
                self.insertImageFile(path)
            return True

        # Office apps put a rendered picture of copied text on the clipboard
        # alongside the text itself. Only paste the image when there is no
        # text, otherwise copying a sentence from Word would paste a picture.
        if source.hasImage() and not self._visibleText(source):
            data = source.imageData()
            # imageData() hands back a QImage on some platforms and a QPixmap
            # on others, so normalise before saving.
            image = data if isinstance(data, QImage) else QImage(data)
            if not image.isNull():
                fname = self._writeImage(image)
                if fname:
                    self._insertImageElement(fname)
                    return True
        return False

    def insertImageFile(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            logger.warning("could not read image %s: %s", path, e)
            return False
        fname = self._writeMedia(os.path.basename(path), data)
        if not fname:
            return False
        self._insertImageElement(fname)
        return True

    def _writeImage(self, image: QImage) -> Optional[str]:
        """Save a clipboard image into the media folder."""
        try:
            as_png = mw.col.get_config_bool(Config.Bool.PASTE_IMAGES_AS_PNG)
        except Exception:
            as_png = False
        fmt, ext = ("PNG", "png") if as_png else ("JPG", "jpg")
        # A default-constructed QBuffer owns its storage. QBuffer(QByteArray())
        # would instead hold a pointer to a temporary that Python frees straight
        # away, leaving the image to be written into released memory.
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        if not image.save(buffer, fmt):
            buffer.close()
            return None
        data = bytes(buffer.data())
        buffer.close()
        name = "io-paste-%s.%s" % (uuid.uuid4().hex[:12], ext)
        return self._writeMedia(name, data)

    def _writeMedia(self, name: str, data: bytes) -> Optional[str]:
        """Register bytes with the media DB, returning the stored filename."""
        try:
            return mw.col.media.write_data(name, data)
        except Exception as e:
            logger.warning("could not add %s to the media folder: %s", name, e)
            tooltip(_("Could not add image to the collection"))
            return None

    def _insertImageElement(self, fname: str) -> None:
        path = os.path.join(mw.col.media.dir(), fname)
        image = QImage(path)
        fmt = QTextImageFormat()
        # Bare filename: the document base URL points at the media folder, and
        # this is also what gets written back into the field.
        fmt.setName(fname)
        if not image.isNull() and image.width() > self.MAX_DISPLAY_WIDTH:
            self._scaleForDisplay(fmt, image)
        self.textCursor().insertImage(fmt)
        self.document().setModified(True)


class FormattingToolbar(QWidget):
    """Formatting controls for the Fields tab.

    One bar serves every field: like a word processor's toolbar it acts on
    whichever field last had focus, and mirrors that field's formatting at the
    cursor.
    """

    TEXT_COLORS = [
        (_("Default"), None),
        (_("Red"), "#e53935"),
        (_("Orange"), "#f57c00"),
        (_("Green"), "#2e7d32"),
        (_("Blue"), "#1e88e5"),
        (_("Purple"), "#8e24aa"),
        (_("Gray"), "#757575"),
    ]
    HIGHLIGHTS = [
        (_("None"), None),
        (_("Yellow"), "#fff176"),
        (_("Green"), "#a5d6a7"),
        (_("Blue"), "#90caf9"),
        (_("Pink"), "#f48fb1"),
        (_("Orange"), "#ffcc80"),
    ]

    def __init__(self, field_getter, parent=None):
        QWidget.__init__(self, parent)
        self.setObjectName("ioFormatBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._field_getter = field_getter
        self._text_color = QColor(self.TEXT_COLORS[1][1])
        self._highlight = QColor(self.HIGHLIGHTS[1][1])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(3)

        self.bold_btn = self._toggleButton(
            "B", _("Bold"), QKeySequence.StandardKey.Bold,
            lambda f: f.toggleBold(), lambda font: font.setBold(True),
        )
        self.italic_btn = self._toggleButton(
            "I", _("Italic"), QKeySequence.StandardKey.Italic,
            lambda f: f.toggleItalic(), lambda font: font.setItalic(True),
        )
        self.underline_btn = self._toggleButton(
            "U", _("Underline"), QKeySequence.StandardKey.Underline,
            lambda f: f.toggleUnderline(), lambda font: font.setUnderline(True),
        )
        self.strike_btn = self._toggleButton(
            "S", _("Strikethrough"), None,
            lambda f: f.toggleStrikeOut(), lambda font: font.setStrikeOut(True),
        )
        self.super_btn = self._toggleButton(
            "x²", _("Superscript"), None,
            lambda f: f.toggleVerticalAlignment(_SUPERSCRIPT), None,
        )
        self.sub_btn = self._toggleButton(
            "x₂", _("Subscript"), None,
            lambda f: f.toggleVerticalAlignment(_SUBSCRIPT), None,
        )
        self.color_btn = self._colorButton(
            _("Text colour"), self.TEXT_COLORS, "_text_color",
            lambda f, c: f.applyTextColor(c), highlight=False,
        )
        self.highlight_btn = self._colorButton(
            _("Highlight"), self.HIGHLIGHTS, "_highlight",
            lambda f, c: f.applyHighlight(c), highlight=True,
        )
        self.clear_btn = self._plainButton(
            _("Clear"), _("Remove formatting from the selection"),
            lambda f: f.clearFormatting(),
        )
        self.image_btn = self._plainButton(
            _("Image…"),
            _("Insert an image. You can also paste or drag one into a field."),
            self._insertImage,
        )

        for widget in (
            self.bold_btn, self.italic_btn, self.underline_btn, self.strike_btn
        ):
            layout.addWidget(widget)
        layout.addWidget(self._separator())
        layout.addWidget(self.super_btn)
        layout.addWidget(self.sub_btn)
        layout.addWidget(self._separator())
        layout.addWidget(self.color_btn)
        layout.addWidget(self.highlight_btn)
        layout.addWidget(self._separator())
        layout.addWidget(self.clear_btn)
        layout.addWidget(self.image_btn)
        layout.addStretch(1)
        self.refreshIcons()

    # -- construction helpers

    def _basicButton(self) -> QToolButton:
        button = QToolButton(self)
        # Never take focus: the field has to keep its cursor and selection.
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(True)
        return button

    def _toggleButton(self, text, name, shortcut, action, style_font):
        button = self._basicButton()
        button.setText(text)
        button.setCheckable(True)
        if style_font is not None:
            font = QFont(button.font())
            style_font(font)
            button.setFont(font)
        if shortcut is not None:
            keys = QKeySequence(shortcut).toString(
                QKeySequence.SequenceFormat.NativeText
            )
            name = "%s (%s)" % (name, keys)
        button.setToolTip(name)
        button.clicked.connect(lambda _checked=False: self._run(action))
        return button

    def _plainButton(self, text, tip, action):
        button = self._basicButton()
        button.setText(text)
        button.setToolTip(tip)
        button.clicked.connect(lambda _checked=False: self._run(action))
        return button

    def _colorButton(self, tip, presets, attr, apply, highlight):
        button = self._basicButton()
        button.setToolTip(tip)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setIconSize(QSize(20, 20))
        button.setProperty("ioHighlight", highlight)
        menu = QMenu(button)
        for label, value in presets:
            color = QColor(value) if value else None
            act = menu.addAction(self._swatchIcon(color), label)
            act.triggered.connect(
                lambda _checked=False, c=color: self._choose(c, attr, apply)
            )
        menu.addSeparator()
        custom = menu.addAction(_("Custom…"))
        custom.triggered.connect(
            lambda _checked=False: self._chooseCustom(attr, apply, tip)
        )
        button.setMenu(menu)
        # Clicking the button itself reapplies the last colour used.
        button.clicked.connect(
            lambda _checked=False: self._run(lambda f: apply(f, getattr(self, attr)))
        )
        return button

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setProperty("ioVSeparator", True)
        line.setFrameShape(QFrame.Shape.VLine)
        return line

    # -- behaviour

    def _run(self, action) -> None:
        field = self._field_getter()
        if field is None:
            return
        action(field)
        field.setFocus()
        self.syncState(field)

    def _choose(self, color, attr, apply) -> None:
        if color is not None:
            setattr(self, attr, color)
            self.refreshIcons()
        self._run(lambda f: apply(f, color))

    def _chooseCustom(self, attr, apply, title) -> None:
        color = QColorDialog.getColor(getattr(self, attr), self.window(), title)
        if color.isValid():
            self._choose(color, attr, apply)

    def _insertImage(self, field) -> None:
        patterns = " ".join("*." + ext for ext in sorted(FIELD_IMAGE_EXTENSIONS))
        path, _filter = QFileDialog.getOpenFileName(
            self.window(),
            _("Insert Image"),
            "",
            _("Images ({patterns})").format(patterns=patterns),
        )
        if path:
            field.insertImageFile(path)

    def syncState(self, field) -> None:
        if field is None:
            return
        fmt = field.currentCharFormat()
        self.bold_btn.setChecked(fmt.fontWeight() > 500)
        self.italic_btn.setChecked(fmt.fontItalic())
        self.underline_btn.setChecked(fmt.fontUnderline())
        self.strike_btn.setChecked(fmt.fontStrikeOut())
        self.super_btn.setChecked(fmt.verticalAlignment() == _SUPERSCRIPT)
        self.sub_btn.setChecked(fmt.verticalAlignment() == _SUBSCRIPT)

    # -- icons

    def refreshIcons(self) -> None:
        self.color_btn.setIcon(self._colorIcon(self._text_color, highlight=False))
        self.highlight_btn.setIcon(self._colorIcon(self._highlight, highlight=True))

    @staticmethod
    def _canvas():
        pixmap = QPixmap(40, 40)
        pixmap.setDevicePixelRatio(2.0)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        return pixmap, painter

    def _colorIcon(self, color, highlight):
        pixmap, painter = self._canvas()
        font = QFont()
        font.setBold(True)
        font.setPixelSize(12)
        painter.setFont(font)
        center = _enumValue(Qt.AlignmentFlag.AlignCenter)
        if highlight:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(1, 3, 18, 14, 3, 3)
            painter.setPen(QColor("#1f2329"))
            painter.drawText(0, 0, 20, 20, center, "ab")
        else:
            painter.setPen(QColor("#e5e7ea") if isNightMode() else QColor("#1f2329"))
            painter.drawText(0, 0, 20, 15, center, "A")
            painter.fillRect(3, 15, 14, 3, color)
        painter.end()
        return QIcon(pixmap)

    def _swatchIcon(self, color):
        pixmap, painter = self._canvas()
        if color is None:
            painter.setPen(QColor("#9aa0a8"))
            painter.drawRoundedRect(3, 3, 14, 14, 3, 3)
            painter.drawLine(5, 15, 15, 5)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(3, 3, 14, 14, 3, 3)
        painter.end()
        return QIcon(pixmap)


class ImgOccEdit(QDialog):
    """Main Image Occlusion Editor dialog"""

    def __init__(self, imgoccadd, parent):
        QDialog.__init__(self)
        if hasattr(mw, "setupDialogGC"):
            mw.setupDialogGC(self)
        self.setWindowFlags(Qt.WindowType.Window)
        self.visible = False
        self.imgoccadd = imgoccadd
        self.parent = parent
        self.mode = "add"
        loadConfig(self)
        self.setupUi()
        restoreGeom(self, "imgoccedit")
        self._theme_hook = None
        self._setupThemeHook()
        try:
            from aqt.gui_hooks import profile_will_close

            profile_will_close.append(self.onProfileUnload)
        except (ImportError, ModuleNotFoundError):
            add_legacy_hook("unloadProfile", self.onProfileUnload)

    def closeEvent(self, event):
        self._on_close()

    def _on_close(self):
        if mw.pm.profile is not None:
            self.deckChooser.cleanup()
            saveGeom(self, "imgoccedit")
        self.visible = False
        if hasattr(self.svg_edit, "cleanup"):  # 2.1.50+
            self.svg_edit.cleanup()  # type: ignore
        self.svg_edit = None
        del self.svg_edit_anim  # might not be gc'd
        self._teardownThemeHook()
        try:
            from aqt.gui_hooks import profile_will_close

            profile_will_close.remove(self.onProfileUnload)
        except (ImportError, ModuleNotFoundError):
            remove_legacy_hook("unloadProfile", self.onProfileUnload)
        QDialog.reject(self)

    def onProfileUnload(self):
        if not sip.isdeleted(self):
            self.close()

    def reject(self):
        if not self.svg_edit:
            return super().reject()
        self.svg_edit.evalWithCallback(
            "svgCanvas.undoMgr.getUndoStackSize() == 0", self._on_reject_callback
        )

    def _on_reject_callback(self, undo_stack_empty: bool):
        if (undo_stack_empty and not self._input_modified()) or askUser(
            "Are you sure you want to close the window? This will discard any unsaved"
            " changes.",
            title="Exit Image Occlusion?",
        ):
            self._on_close()

    def _input_modified(self) -> bool:
        tags_modified = self.tags_edit.isModified()
        fields_modified = any(
            field_edit.document().isModified()  # type: ignore
            for field_edit in self.findChildren(IOFieldEdit)
        )
        return tags_modified or fields_modified

    # Theming

    def _setupThemeHook(self):
        """Follow Anki's theme while the editor is open"""
        try:
            from aqt.gui_hooks import theme_did_change
        except (ImportError, ModuleNotFoundError):
            return
        self._theme_hook = self.onThemeChange
        theme_did_change.append(self._theme_hook)

    def _teardownThemeHook(self):
        if not self._theme_hook:
            return
        try:
            from aqt.gui_hooks import theme_did_change

            theme_did_change.remove(self._theme_hook)
        except (ImportError, ModuleNotFoundError, ValueError):
            pass
        self._theme_hook = None

    def onThemeChange(self):
        # Anki fires this from a progress handler, by which point the dialog
        # may already be gone. Guarding here avoids the RuntimeError that
        # issue #251 tracked.
        if sip.isdeleted(self):
            return
        self.applyTheme()

    def applyTheme(self):
        night = isNightMode()
        self.setStyleSheet(qtStylesheet(night))
        bar = getattr(self, "format_bar", None)
        if bar is not None:
            bar.refreshIcons()
        if self.svg_edit and not sip.isdeleted(self.svg_edit):
            self.svg_edit.eval(
                "document.documentElement.dataset.ioTheme = '%s';"
                % ("dark" if night else "light")
            )

    # Field formatting

    def _activeField(self):
        """The field the formatting toolbar acts on."""
        field = getattr(self, "_active_field", None)
        if field is not None and not sip.isdeleted(field):
            return field
        order = getattr(self, "_field_order", None)
        field = self.tedit.get(order[0]) if order else None
        self._active_field = field
        return field

    def _onFieldFocused(self, field):
        self._active_field = field
        self.format_bar.syncState(field)

    def _onFieldFormatChanged(self, field):
        if field is getattr(self, "_active_field", None):
            self.format_bar.syncState(field)

    def setupUi(self):
        """Set up ImgOccEdit UI"""
        # Main widgets aside from fields
        self.svg_edit = ImgOccWebView(parent=self)
        page = ImgOccWebPage(self.svg_edit._onBridgeCmd)
        # Hold a reference of our own so the page is never garbage collected;
        # older Anki versions also read it back from _page.
        self.svg_edit._io_page = page
        self.svg_edit._page = page
        self.svg_edit.setPage(page)

        self.svg_edit.escape_pressed.connect(self.reject)

        self.tags_edit = tagedit.TagEdit(self)
        self.tags_label = QLabel(_("Tags"))
        self.tags_label.setProperty("ioMuted", True)
        self.deck_container = QWidget()
        self.deckChooser = deckchooser.DeckChooser(mw, self.deck_container, label=True)
        deck_button = getattr(self.deckChooser, "deck", None)
        if deck_button is not None:
            deck_button.setAutoDefault(False)

        # workaround for tab focus order issue of the tags entry
        # (this particular section is only needed when the quick deck
        # buttons add-on is installed)
        if self.deck_container.layout().children():  # multiple deck buttons
            for i in range(self.deck_container.layout().children()[0].count()):
                try:
                    item = self.deck_container.layout().children()[0].itemAt(i)
                    # remove Tab focus manually:
                    item.widget().setFocusPolicy(Qt.FocusPolicy.ClickFocus)
                    item.widget().setAutoDefault(False)
                except AttributeError:
                    pass

        # Button row widgets
        self.bottom_label = QLabel()
        button_box = QDialogButtonBox(Qt.Orientation.Horizontal, self)
        button_box.setCenterButtons(False)

        image_btn = QPushButton(_("Change &Image"))
        image_btn.clicked.connect(self.changeImage)
        image_btn.setIcon(QIcon(os.path.join(ICONS_PATH, "add.png")))
        image_btn.setIconSize(QSize(16, 16))
        image_btn.setAutoDefault(False)

        self.occl_tp_select = QComboBox()
        self.occl_tp_select.addItem(_("Don't Change"), "Don't Change")
        self.occl_tp_select.addItem(_("Hide All, Guess One"), "Hide All, Guess One")
        self.occl_tp_select.addItem(_("Hide One, Guess One"), "Hide One, Guess One")

        self.edit_btn = button_box.addButton(
            _("&Edit Cards"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.new_btn = button_box.addButton(
            _("&Add New Cards"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.ao_btn = button_box.addButton(
            _("Hide &All, Guess One"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.oa_btn = button_box.addButton(
            _("Hide &One, Guess One"), QDialogButtonBox.ButtonRole.ActionRole
        )
        help_button = button_box.addButton(
            _("&?"), QDialogButtonBox.ButtonRole.ActionRole
        )
        help_button.setProperty("ioIcon", True)
        close_button = button_box.addButton(
            _("&Close"), QDialogButtonBox.ButtonRole.RejectRole
        )

        image_tt = _(
            "Switch to a different image while preserving all of the shapes and fields"
        )
        dc_tt = _("Preserve existing occlusion type")
        edit_tt = _("Edit all cards using current mask shapes and field entries")
        new_tt = _("Create new batch of cards without editing existing ones")
        ao_tt = _(
            "Generate cards with nonoverlapping information, where all"
            "<br>labels are hidden on the front and one revealed on the"
            " back"
        )
        oa_tt = _(
            "Generate cards with overlapping information, where one<br>"
            "label is hidden on the front and revealed on the back"
        )
        close_tt = _("Close Image Occlusion Editor without generating cards")

        image_btn.setToolTip(image_tt)
        self.edit_btn.setToolTip(edit_tt)
        self.new_btn.setToolTip(new_tt)
        self.ao_btn.setToolTip(ao_tt)
        self.oa_btn.setToolTip(oa_tt)
        close_button.setToolTip(close_tt)
        self.occl_tp_select.setItemData(0, dc_tt, Qt.ItemDataRole.ToolTipRole)
        self.occl_tp_select.setItemData(1, ao_tt, Qt.ItemDataRole.ToolTipRole)
        self.occl_tp_select.setItemData(2, oa_tt, Qt.ItemDataRole.ToolTipRole)

        for btn in [
            image_btn,
            self.edit_btn,
            self.new_btn,
            self.ao_btn,
            self.oa_btn,
            help_button,
            close_button,
        ]:
            btn.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            btn.setDefault(False)
            btn.setAutoDefault(False)

        # self.ao_btn.setDefault(True)

        self.edit_btn.clicked.connect(self.editNote)
        self.new_btn.clicked.connect(self.new)
        self.ao_btn.clicked.connect(self.addAO)
        self.oa_btn.clicked.connect(self.addOA)
        help_button.clicked.connect(self.onHelp)
        close_button.clicked.connect(self.close)

        # Set basic layout up

        # Button row
        bottom_hbox = QHBoxLayout()
        bottom_hbox.setContentsMargins(14, 10, 14, 12)
        bottom_hbox.setSpacing(8)
        bottom_hbox.addWidget(image_btn)
        bottom_hbox.insertStretch(1, stretch=1)
        bottom_hbox.addWidget(self.bottom_label)
        bottom_hbox.addWidget(self.occl_tp_select)
        bottom_hbox.addWidget(button_box)

        self.bottom_bar = QWidget()
        self.bottom_bar.setObjectName("ioBottomBar")
        self.bottom_bar.setLayout(bottom_hbox)

        bottom_sep = QFrame()
        bottom_sep.setProperty("ioSeparator", True)
        bottom_sep.setFrameShape(QFrame.Shape.HLine)

        # Tab 1
        vbox1 = QVBoxLayout()
        vbox1.setContentsMargins(0, 0, 0, 0)

        svg_edit_loader = QLabel(_("Loading..."))
        svg_edit_loader.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loader_icon = os.path.join(ICONS_PATH, "loader.gif")
        anim = QMovie(loader_icon)
        svg_edit_loader.setMovie(anim)
        anim.start()
        self.svg_edit_loader = svg_edit_loader
        self.svg_edit_anim = anim

        vbox1.addWidget(self.svg_edit, stretch=1)
        vbox1.addWidget(self.svg_edit_loader, stretch=1)

        # Tab 2
        # Rows are variable and added by setupFields() at a later point. The
        # form lives in a scroll area so that note types with many fields stay
        # usable in a small window.
        self.fields_form = QFormLayout()
        self.fields_form.setContentsMargins(18, 16, 18, 16)
        self.fields_form.setSpacing(10)
        self.fields_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        self.fields_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        fields_inner = QWidget()
        fields_inner.setLayout(self.fields_form)
        self.fields_scroll = QScrollArea()
        self.fields_scroll.setWidgetResizable(True)
        self.fields_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.fields_scroll.setWidget(fields_inner)

        self._active_field = None
        self.format_bar = FormattingToolbar(self._activeField, self)

        self.vbox2 = QVBoxLayout()
        self.vbox2.setContentsMargins(0, 0, 0, 0)
        self.vbox2.setSpacing(0)
        self.vbox2.addWidget(self.format_bar)
        self.vbox2.addWidget(self.fields_scroll)

        # Main Tab Widget
        tab1 = QWidget()
        tab1.setContentsMargins(0, 0, 0, 0)
        self.tab2 = QWidget()
        tab1.setLayout(vbox1)
        self.tab2.setLayout(self.vbox2)
        self.tab_widget = QTabWidget()
        self.tab_widget.setContentsMargins(0, 0, 0, 0)
        self.tab_widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.tab_widget.addTab(tab1, _("&Masks Editor"))
        self.tab_widget.addTab(self.tab2, _("&Fields"))
        self.tab_widget.setTabToolTip(1, _("Include additional information (optional)"))
        self.tab_widget.setTabToolTip(0, _("Create image occlusion masks (required)"))

        # Main Window
        vbox_main = QVBoxLayout()
        vbox_main.setContentsMargins(10, 8, 10, 0)
        vbox_main.setSpacing(0)
        vbox_main.addWidget(self.tab_widget)
        vbox_main.addWidget(bottom_sep)
        vbox_main.addWidget(self.bottom_bar)
        self.setLayout(vbox_main)
        self.setMinimumWidth(820)
        self.setMinimumHeight(560)
        self.resize(1100, 780)
        self.tab_widget.setCurrentIndex(0)
        self.svg_edit.setFocus()
        self.showSvgEdit(False)
        self.applyTheme()

        # Define and connect key bindings

        # Field focus hotkeys
        for i in range(1, 10):
            QShortcut(QKeySequence("Ctrl+%i" % i), self).activated.connect(
                lambda f=i - 1: self.focusField(f)
            )
        # Other hotkeys
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(
            lambda: self.defaultAction(True)
        )
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self).activated.connect(
            lambda: self.addOA(True)
        )
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(self.switchTabs)
        QShortcut(QKeySequence("Ctrl+r"), self).activated.connect(self.resetMainFields)
        QShortcut(QKeySequence("Ctrl+Shift+r"), self).activated.connect(
            self.resetAllFields
        )
        QShortcut(QKeySequence("Ctrl+Shift+t"), self).activated.connect(self.focusTags)
        QShortcut(QKeySequence("Ctrl+f"), self).activated.connect(self.fitImageCanvas)

    # Various actions that act on / interact with the ImgOccEdit UI:

    # Note actions

    def changeImage(self):
        self.imgoccadd.onChangeImage()
        self.fitImageCanvas()

    def defaultAction(self, close):
        if self.mode == "add":
            self.addAO(close)
        else:
            self.editNote()

    def addAO(self, close=False):
        self.imgoccadd.onAddNotesButton("ao", close)

    def addOA(self, close=False):
        self.imgoccadd.onAddNotesButton("oa", close)

    def new(self, close=False):
        choice = self.occl_tp_select.currentData()
        self.imgoccadd.onAddNotesButton(choice, close)

    def editNote(self):
        choice = self.occl_tp_select.currentData()
        self.imgoccadd.onEditNotesButton(choice)

    def onHelp(self):
        if self.mode == "add":
            ioHelp("add", parent=self)
        else:
            ioHelp("edit", parent=self)

    # Window state

    def resetFields(self):
        """Reset all widgets. Needed for changes to the note type"""
        # takeAt rather than removeRow: the tags and deck widgets are long
        # lived and get re-added by the next setupFields() call, so they must
        # not be deleted here.
        while self.fields_form.count():
            item = self.fields_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.tedit = {}
        self.tlabel = {}
        self._field_order = []
        self._active_field = None

    def setupFields(self, flds):
        """Setup dialog text edits based on note type fields"""
        self.tedit = {}
        self.tlabel = {}
        self.flds = flds
        # Focus order for the Ctrl+1..9 shortcuts, which used to index the
        # layout directly. A QFormLayout has no equivalent traversal.
        self._field_order = []
        for i in flds:
            if i["name"] in self.ioflds_priv:
                continue
            tedit = IOFieldEdit()
            tedit.setMinimumHeight(64)
            label = QLabel(i["name"])
            label.setProperty("ioMuted", True)
            self.fields_form.addRow(label, tedit)
            self.tedit[i["name"]] = tedit
            self.tlabel[i["name"]] = label
            self._field_order.append(i["name"])
            tedit.focused.connect(self._onFieldFocused)
            tedit.formatChanged.connect(self._onFieldFormatChanged)

        self.fields_form.addRow(self.tags_label, self.tags_edit)
        self.fields_form.addRow(self.deck_container)
        # switch Tab focus order of deckchooser and tags_edit (
        # for some reason it's the wrong way around by default):
        deck_button = getattr(self.deckChooser, "deck", None)
        if deck_button is not None:
            self.tab2.setTabOrder(self.tags_edit, deck_button)

    def switchToMode(self, mode):
        """Toggle between add and edit layouts"""
        hide_on_add = [self.occl_tp_select, self.edit_btn, self.new_btn]
        hide_on_edit = [self.ao_btn, self.oa_btn]
        self.mode = mode
        for i in list(self.tedit.values()):
            i.show()
        for i in list(self.tlabel.values()):
            i.show()
        if mode == "add":
            for i in hide_on_add:
                i.hide()
            for i in hide_on_edit:
                i.show()
            dl_txt = _("Deck")
            ttl = _("Image Occlusion Enhanced - Add Mode")
            bl_txt = _("Add Cards:")
            self._setPrimaryButton(self.ao_btn)
        else:
            for i in hide_on_add:
                i.show()
            for i in hide_on_edit:
                i.hide()
            for i in self.sconf["skip"]:
                if i in list(self.tedit.keys()):
                    self.tedit[i].hide()
                    self.tlabel[i].hide()
            dl_txt = _("Deck for <i>Add new cards</i>")
            ttl = _("Image Occlusion Enhanced - Editing Mode")
            bl_txt = _("Type:")
            self._setPrimaryButton(self.edit_btn)
        deck_label = getattr(self.deckChooser, "deckLabel", None)
        if deck_label is not None:
            deck_label.setText(dl_txt)
        self.setWindowTitle(ttl)
        self.bottom_label.setText(bl_txt)

    def _setPrimaryButton(self, primary):
        """Give the mode's main action visual emphasis.

        QSS matches on the dynamic property, and Qt only re-evaluates that
        after an unpolish/polish cycle, so the style has to be refreshed by
        hand rather than just setting the property.
        """
        for btn in (self.ao_btn, self.oa_btn, self.edit_btn, self.new_btn):
            btn.setProperty("ioPrimary", btn is primary)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def showSvgEdit(self, state):
        if not state:
            self.svg_edit.hide()
            self.svg_edit_anim.start()
            self.svg_edit_loader.show()
        else:
            self.svg_edit_anim.stop()
            self.svg_edit_loader.hide()
            self.svg_edit.show()

    # Other actions

    def switchTabs(self):
        currentTab = self.tab_widget.currentIndex()
        if currentTab == 0:
            self.tab_widget.setCurrentIndex(1)
            if isinstance(QApplication.focusWidget(), QPushButton):
                self.tedit[self.ioflds["hd"]].setFocus()
        else:
            self.tab_widget.setCurrentIndex(0)

    def focusField(self, idx):
        """Focus field by index number"""
        self.tab_widget.setCurrentIndex(1)
        if idx < 0 or idx >= len(self._field_order):
            return
        target = self.tedit[self._field_order[idx]]
        self.fields_scroll.ensureWidgetVisible(target)
        target.setFocus()

    def focusTags(self):
        self.tab_widget.setCurrentIndex(1)
        self.tags_edit.setFocus()

    def resetMainFields(self):
        """Reset all fields aside from sticky ones"""
        for i in self.flds:
            fn = i["name"]
            if fn in self.ioflds_priv or fn in self.ioflds_prsv:
                continue
            self.tedit[fn].setFieldHtml("")

    def resetAllFields(self):
        """Reset all fields"""
        self.resetMainFields()
        for i in self.ioflds_prsv:
            self.tedit[i].setFieldHtml("")

    def fitImageCanvas(self):
        """Fit the canvas to its background image.

        Waits for the image to finish loading rather than guessing with a
        timeout, which is what made the editor so often open at a useless zoom
        level (issue #92). Fits immediately when the image is already decoded,
        so this is also the right thing to bind to the Ctrl+F shortcut.
        """
        if not self.svg_edit:
            return
        self.svg_edit.eval(
            "if (window.ioFitWhenReady) { window.ioFitWhenReady(); }"
            " else { svgCanvas.zoomChanged('', 'canvas'); }"
        )
