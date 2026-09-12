/* 
Image Occlusion Enhanced Add-on for Anki

Copyright (C) 2016-2022  Aristotelis P. <https://glutanimate.com/>
Copyright (C) 2012-2015  Tiago Barroso <tmbb@campus.ul.pt>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version, with the additions
listed at the end of the license file that accompanied this program.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

NOTE: This program is subject to certain additional terms pursuant to
Section 7 of the GNU Affero General Public License.  You should have
received a copy of these additional terms immediately following the
terms and conditions of the GNU Affero General Public License that
accompanied this program.

If not, please request a copy through one of the means of contact
listed here: <https://glutanimate.com/contact/>.

Any modifications to this file must keep this entire header intact.
*/

const NoteEditor = require("anki/NoteEditor");

class ImageOcclusionEditorAdapter {
  /**
   * Tag the hidden ID field so editor.css can hide it.
   *
   * This runs as soon as a note is loaded, which can be before the editor has
   * finished constructing its fields. Reading `.element` off a field that is
   * not ready yet threw "Cannot read properties of undefined (reading 'then')"
   * and left the ID field visible, so retry briefly instead of assuming the
   * field is there. `element` is a promise in current Anki but has been a
   * plain node in the past, so handle both.
   */
  markIdField(index, remainingAttempts = 20) {
    const apply = (element) => {
      if (element && element.classList) {
        element.classList.add("ionote-field-id");
      }
    };

    const instance = NoteEditor.instances && NoteEditor.instances[0];
    const field = instance && instance.fields && instance.fields[index];
    const element = field && field.element;

    if (element && typeof element.then === "function") {
      element.then(apply).catch(() => {});
      return;
    }
    if (element && element.nodeType === 1) {
      apply(element);
      return;
    }
    if (remainingAttempts > 0) {
      setTimeout(() => this.markIdField(index, remainingAttempts - 1), 50);
    }
  }
}

globalThis.imageOcclusion = new ImageOcclusionEditorAdapter();
