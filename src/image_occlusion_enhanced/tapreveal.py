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
Tap to reveal: lets the reviewer uncover one mask at a time by tapping it,
and cover it again with another tap.

A script in the card templates loads the card's mask image once more, as
live shapes, and lays it exactly over the image. Wherever the image cannot
be loaded that way (some mobile apps do not allow it), the card works
exactly as before.

The script sits between two markers at the end of both templates, so that
later versions can replace it without touching anything else in a template
the user may have customized.

Plain Python without Anki imports, so that it can be unit tested.
"""

import re

TAP_TO_REVEAL_VERSION = 2
TAP_TO_REVEAL_BEGIN = "<!-- Image Occlusion Enhanced: tap to reveal (v%d) -->"
TAP_TO_REVEAL_END = "<!-- /Image Occlusion Enhanced: tap to reveal -->"
_TAP_TO_REVEAL_RE = re.compile(
    r"\n*<!-- Image Occlusion Enhanced: tap to reveal \(v\d+\) -->.*?"
    r"<!-- /Image Occlusion Enhanced: tap to reveal -->\n*",
    re.S,
)

tap_to_reveal_script = """\
<script>
(function () {
  var overlay = document.getElementById("io-overlay");
  var img = overlay && overlay.querySelector("img");
  if (!img || img.getAttribute("data-io-tap") || !window.DOMParser) return;
  img.setAttribute("data-io-tap", "1");
  var src = img.getAttribute("src");
  if (!src) return;

  function load(url, done) {
    function viaXhr() {
      try {
        var xhr = new XMLHttpRequest();
        xhr.onload = function () {
          if (xhr.status === 200 || (xhr.status === 0 && xhr.responseText)) {
            done(xhr.responseText);
          }
        };
        xhr.open("GET", url, true);
        xhr.send();
      } catch (e) {}
    }
    if (!window.fetch) return viaXhr();
    fetch(url).then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.text();
    }).then(done, viaXhr);
  }

  function hasClass(node, name) {
    return (" " + (node.getAttribute("class") || "") + " ").indexOf(" " + name + " ") !== -1;
  }

  function toggleClass(node, name) {
    var classes = (node.getAttribute("class") || "").split(/\\s+/).filter(Boolean);
    var at = classes.indexOf(name);
    if (at === -1) classes.push(name); else classes.splice(at, 1);
    node.setAttribute("class", classes.join(" "));
  }

  load(src, function (text) {
    var parsed = new DOMParser().parseFromString(text, "image/svg+xml");
    var root = parsed.documentElement;
    if (!root || root.nodeName !== "svg" || parsed.getElementsByTagName("parsererror").length) return;
    var svg = document.importNode(root, true);
    var scripts = svg.getElementsByTagName("script");
    while (scripts.length) scripts[0].parentNode.removeChild(scripts[0]);
    var layer = null;
    for (var node = svg.firstElementChild; node; node = node.nextElementSibling) {
      if (node.nodeName === "g") layer = node;
    }
    if (!layer) return;
    var masks = [];
    for (var mask = layer.firstElementChild; mask; mask = mask.nextElementSibling) {
      if (["title", "desc", "text"].indexOf(mask.nodeName) === -1) masks.push(mask);
    }
    if (!masks.length) return;
    var width = parseFloat(svg.getAttribute("width"));
    var height = parseFloat(svg.getAttribute("height"));
    if (!svg.getAttribute("viewBox")) {
      if (!(width > 0 && height > 0)) return;
      svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    }
    svg.setAttribute("preserveAspectRatio", "none");
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.setAttribute("class", "io-tap-layer");
    svg.style.position = "absolute";
    svg.style.overflow = "visible";
    svg.style.pointerEvents = "none";
    var style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent =
      ".io-tap-layer .io-mask { cursor: pointer; pointer-events: all; }" +
      ".io-tap-layer .io-revealed, .io-tap-layer .io-revealed * {" +
      " fill-opacity: 0 !important; stroke-dasharray: 6 4; }";
    svg.insertBefore(style, svg.firstChild);
    masks.forEach(function (mask) {
      if (!hasClass(mask, "io-mask")) toggleClass(mask, "io-mask");
      mask.addEventListener("click", function (event) {
        event.stopPropagation();
        toggleClass(mask, "io-revealed");
      });
    });

    if (window.getComputedStyle(overlay).position === "static") {
      overlay.style.position = "relative";
    }
    function place() {
      if (!svg.parentNode) return;
      var box = overlay.getBoundingClientRect();
      var picture = img.getBoundingClientRect();
      // While the masks are toggled off there is nothing to measure; keep
      // the last position for when they are shown again.
      if (!picture.width || !picture.height) return;
      svg.style.left = picture.left - box.left - overlay.clientLeft + "px";
      svg.style.top = picture.top - box.top - overlay.clientTop + "px";
      svg.style.width = picture.width + "px";
      svg.style.height = picture.height + "px";
    }
    overlay.appendChild(svg);
    place();
    img.style.visibility = "hidden";
    img.addEventListener("load", place);
    if (window.ResizeObserver) new ResizeObserver(place).observe(img);
    // Older web views do not always report the image's size when the masks
    // are toggled back on, so look again whenever they are shown or hidden.
    if (window.MutationObserver) {
      new MutationObserver(function () {
        window.requestAnimationFrame(place);
      }).observe(overlay, {attributes: true, attributeFilter: ["style", "class"]});
    }
    window.ioTapToRevealPlace = place;
    if (!window.ioTapToRevealListening) {
      window.ioTapToRevealListening = true;
      window.addEventListener("resize", function () {
        if (window.ioTapToRevealPlace) window.ioTapToRevealPlace();
      });
    }
  });
})();
</script>"""

tap_to_reveal_html = "%s\n%s\n%s" % (
    TAP_TO_REVEAL_BEGIN % TAP_TO_REVEAL_VERSION,
    tap_to_reveal_script,
    TAP_TO_REVEAL_END,
)


def with_tap_to_reveal(template_html: str) -> str:
    """The template with the current tap-to-reveal script at its end"""
    stripped = _TAP_TO_REVEAL_RE.sub("\n", template_html).rstrip("\n")
    return stripped + "\n\n" + tap_to_reveal_html + "\n"
