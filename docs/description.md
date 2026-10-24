**Image Occlusion Enhanced (Continued)** lets you create cards that hide parts of an image to test your knowledge of what is underneath: image-based cloze deletions, made in a full mask editor.

This is a continued and modified version of [Image Occlusion Enhanced](https://ankiweb.net/shared/info/1374772155) by Glutanimate, whose last release was in 2022. It is maintained separately and is not made or endorsed by the original author. Your existing image occlusion notes, note type and settings keep working: they are stored in your collection, not in the add-on. If the original add-on is installed as well, it is switched off for you.

![The mask editor after Mask Text covered the labels of a diagram](https://raw.githubusercontent.com/Punnawit9285/image-occlusion-enhanced/main/screenshots/editor-mask-text.png)

### What it does

- **Draw masks** over an image with rectangles, ellipses, polygons, freehand shapes and paths, and group shapes into a single card. Add labels, lines and arrows in their own layer.
- **Three card types**: *Hide All, Guess One* and *Hide One, Guess One* make a card for every mask; *Hide All, Guess All* makes one card that asks about the whole image.
- **Mask Text**: one click finds the text labels in an image and covers each with a mask. It uses Tesseract where installed, and otherwise the text recognition built into macOS and Windows.
- **Tap to reveal**: while reviewing, tap any mask to uncover just that one, and tap again to cover it.
- **More fields**: Header, Footer, Remarks, Sources and two extra fields, with formatting and pictures.
- **Convert notes** to and from Anki's built-in Image Occlusion (Anki 23.10 and later), keeping their scheduling and review history: *Browse* → *Notes* → *Image Occlusion*.

![Tapping masks during review uncovers them one at a time](https://raw.githubusercontent.com/Punnawit9285/image-occlusion-enhanced/main/screenshots/review-tap-to-reveal.png)

### Getting started

Open *Add*, choose any note type, and click the *I/O* button in the editor (Ctrl+Shift+O). Pick an image, cover what you want to be tested on, and click one of the *Add Cards* buttons. To change cards later, open one in the *Browse* window or while reviewing (*Edit*) and click *I/O* again.

### Compared with Anki's built-in Image Occlusion

Anki has had its own Image Occlusion since version 23.10. It needs no add-on and saves no mask images. This add-on offers more drawing tools, fields and card types, Mask Text and tap to reveal. You can move notes between the two at any time without losing their review history.

### Compatibility

Anki 2.1.50 and later; tested on Anki 2.1.50, 23.12 and 26.09. Cards work in all Anki apps. Tap to reveal is not available where an app does not let cards load their mask images, and those cards then behave as before. Converting notes needs Anki 23.10 or later.

### Changes, problems and source code

The [changelog](https://github.com/Punnawit9285/image-occlusion-enhanced/blob/main/CHANGELOG.md) lists every change. Please report problems on the [issue tracker](https://github.com/Punnawit9285/image-occlusion-enhanced/issues), with your Anki version and operating system. The source code is on [GitHub](https://github.com/Punnawit9285/image-occlusion-enhanced).

### Credits and license

*Image Occlusion Enhanced* is Copyright © 2012-2015 Tiago Barroso, © 2013 Steve AW and © 2016-2022 Aristotelis P. (Glutanimate), with code contributions from Damien Elmes, Kyle Mills, James Kraus and Matt Restko. It is based on Image Occlusion 2.0 by Tiago Barroso and Simple Picture Occlusion by Steve AW. This continued version is modified by Punnawit9285.

Licensed under the GNU AGPLv3, extended by a number of additional terms; see the [LICENSE](https://github.com/Punnawit9285/image-occlusion-enhanced/blob/main/LICENSE) file. This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY. It ships with SVG-Edit (MIT license), imagesize.py (MIT license), imghdr from the Python standard library (PSF license) and pathseg (BSD-style license).
