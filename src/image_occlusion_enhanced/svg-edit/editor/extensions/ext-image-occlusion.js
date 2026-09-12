/*
 * ext-image-occlusion.js
 *
 * Licensed under the GNU AGPLv3
 *
 * Copyright(c) 2012-2015 tmbb
 * Copyright(c) 2016-2017 Glutanimate
 *
 * This file is part of Image Occlusion Enhanced for Anki
 *
 */

svgEditor.addExtension("Image Occlusion (Anki)", function() {
      return {
        name: "Image Occlusion",
  			svgicons: "extensions/image-occlusion-icon.xml",
  			buttons: [{
          id: "set_zoom_canvas",
          type: "mode",
          title: "Fit image to canvas",
          key: "F",
          events: {
            "click": function() {
              svgCanvas.zoomChanged('', 'canvas');
            }
          }
        }],
		};
});

// Fit the canvas to its background image, once that is actually possible.
//
// Fitting has two preconditions, and missing either one is what made the
// editor so reliably open at a useless zoom level (issue #92):
//
//   1. the background image has to be decoded, otherwise there are no
//      dimensions to fit to; and
//   2. the work area has to have been laid out. Anki keeps the web view
//      hidden behind a loading spinner until the editor reports ready, and
//      fitting against a zero-sized work area collapses the zoom to ~0.1%.
//
// The add-on used to paper over this with two guessed setTimeouts on the
// Python side. Waiting for the real conditions removes the guesswork; the
// attempt limit and timeout are only backstops, so a broken image or a window
// that never becomes visible can't leave the editor unusable.
window.ioFitWhenReady = function (callback) {
  var done = false;
  var settleTimer = null;
  var observer = null;

  function fit() {
    try {
      svgCanvas.zoomChanged('', 'canvas');
    } catch (e) {
      // A failed fit must never stop the editor from being shown.
    }
  }

  function stopSettling() {
    if (observer) { observer.disconnect(); observer = null; }
    if (settleTimer) { clearTimeout(settleTimer); settleTimer = null; }
    document.removeEventListener('mousedown', stopSettling, true);
    document.removeEventListener('keydown', stopSettling, true);
    document.removeEventListener('wheel', stopSettling, true);
  }

  function settle() {
    // Keep re-fitting while the work area is still changing size. Anki reveals
    // the web view only after the editor reports ready, and the panels below
    // it settle over several frames after that, so a single fit at any one
    // moment is a coin flip - which is exactly what issue #92 describes.
    var wa = document.getElementById('workarea');
    if (!wa || typeof ResizeObserver === 'undefined') return;
    observer = new ResizeObserver(function () { fit(); });
    observer.observe(wa);
    settleTimer = setTimeout(stopSettling, 3000);
    // Any real interaction means the user owns the zoom from here on.
    document.addEventListener('mousedown', stopSettling, true);
    document.addEventListener('keydown', stopSettling, true);
    document.addEventListener('wheel', stopSettling, true);
  }

  function finish() {
    if (done) return;
    done = true;
    fit();
    settle();
    if (callback) callback();
  }

  var bg = document.querySelector('#canvasBackground image');
  var href = bg && (bg.getAttribute('xlink:href') || bg.getAttribute('href'));
  if (!href) {
    finish();
    return;
  }

  // A detached Image gives a dependable load event even when the <image> in
  // the canvas has already started fetching.
  var probe = new Image();
  probe.onload = finish;
  probe.onerror = finish;
  probe.src = href;
  if (probe.complete) finish();

  setTimeout(finish, 5000);
};

svgEditor.ready(function () {
  // Report readiness first: Anki only reveals the web view in response to
  // this, and the fit above has to happen after that reveal.
  pycmd("svgEditDone");
});
