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
    QBuffer,
    QByteArray,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QIcon,
    QImage,
    QIODevice,
    QKeySequence,
    QLabel,
    QMovie,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSize,
    Qt,
    QTabWidget,
    QTextEdit,
    QTextImageFormat,
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


class IOFieldEdit(QTextEdit):
    """Field entry widget that accepts pasted and dropped images.

    Anki stores field content as HTML, so images live in the collection's media
    folder and are referenced as <img src="filename">. Using a rich text widget
    means they show up as pictures while editing instead of as a bare file path,
    which is what users kept running into (issues #276, #310).

    The document's base URL is the media folder, so a bare filename in an
    img src resolves both when loading a note and when serialising back out.
    """

    # Images wider than this are scaled down for display only; the stored
    # markup is untouched, so cards still get the full-resolution file.
    MAX_DISPLAY_WIDTH = 320

    def __init__(self, parent=None):
        QTextEdit.__init__(self, parent)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setAcceptDrops(True)
        self._original = ""
        try:
            self.document().setBaseUrl(
                QUrl.fromLocalFile(os.path.join(mw.col.media.dir(), ""))
            )
        except Exception:
            # No collection open yet; images simply will not preview.
            pass

    # -- content round-tripping

    def setFieldHtml(self, text: str) -> None:
        """Load a field's stored HTML, remembering it for preservation."""
        self._original = text or ""
        self.setHtml(self._original)
        self.document().setModified(False)

    def fieldHtml(self) -> str:
        """Serialise back to the minimal HTML the note type expects.

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
            name = fmt.toImageFormat().name()
            if not name:
                return ""
            return path_to_img_element(name)
        text = html.escape(fragment.text(), quote=False)
        if not text:
            return ""
        if fmt.fontUnderline():
            text = "<u>%s</u>" % text
        if fmt.fontItalic():
            text = "<i>%s</i>" % text
        if fmt.fontWeight() > 500:
            text = "<b>%s</b>" % text
        return text

    # -- image input

    def canInsertFromMimeData(self, source) -> bool:
        if source.hasImage() or self._imagePaths(source):
            return True
        return QTextEdit.canInsertFromMimeData(self, source)

    def insertFromMimeData(self, source) -> None:
        if self._insertImages(source):
            return
        # Deliberately plain: the serialiser above only emits a small set of
        # tags, so arbitrary pasted markup could not be round-tripped anyway.
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
            if ext in SUPPORTED_EXTENSIONS and os.path.isfile(path):
                paths.append(path)
        return paths

    def _insertImages(self, source) -> bool:
        inserted = False
        for path in self._imagePaths(source):
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError as e:
                logger.warning("could not read dropped image %s: %s", path, e)
                continue
            fname = self._writeMedia(os.path.basename(path), data)
            if fname:
                self._insertImageElement(fname)
                inserted = True
        if inserted:
            return True

        if source.hasImage():
            # imageData() hands back a QImage on some platforms and a QPixmap
            # on others, so normalise before saving.
            data = source.imageData()
            image = data if isinstance(data, QImage) else QImage(data)
            if not image.isNull():
                fname = self._writeImage(image)
                if fname:
                    self._insertImageElement(fname)
                    return True
        return False

    def _writeImage(self, image: QImage) -> Optional[str]:
        """Save a clipboard image into the media folder."""
        try:
            as_png = mw.col.get_config_bool(Config.Bool.PASTE_IMAGES_AS_PNG)
        except Exception:
            as_png = False
        fmt, ext = ("PNG", "png") if as_png else ("JPG", "jpg")
        buffer = QBuffer(QByteArray())
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
            scale = self.MAX_DISPLAY_WIDTH / float(image.width())
            fmt.setWidth(self.MAX_DISPLAY_WIDTH)
            fmt.setHeight(image.height() * scale)
        self.textCursor().insertImage(fmt)
        self.document().setModified(True)


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
        if self.svg_edit and not sip.isdeleted(self.svg_edit):
            self.svg_edit.eval(
                "document.documentElement.dataset.ioTheme = '%s';"
                % ("dark" if night else "light")
            )

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

        self.vbox2 = QVBoxLayout()
        self.vbox2.setContentsMargins(0, 0, 0, 0)
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
