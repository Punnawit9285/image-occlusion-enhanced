<p align="center"><img src="screenshots/logo.png" width=381 height=224></p>

<h2 align="center">Image Occlusion Enhanced for Anki</h2>

<p align="center">
<a title="Latest (pre-)release" href="https://github.com/glutanimate/image-occlusion-enhanced/releases"><img src ="https://img.shields.io/github/release-pre/glutanimate/image-occlusion-enhanced.svg?colorB=brightgreen"></a>
<a title="License: GNU AGPLv3" href="https://github.com/glutanimate/image-occlusion-enhanced/blob/master/LICENSE"><img  src="https://img.shields.io/badge/license-GNU AGPLv3-green.svg"></a>
<a title="Rate on AnkiWeb" href="https://ankiweb.net/shared/info/1374772155"><img src="https://glutanimate.com/logos/ankiweb-rate.svg"></a>
<br>
<a title="Buy me a coffee :)" href="https://ko-fi.com/X8X0L4YV"><img src="https://img.shields.io/badge/ko--fi-contribute-%23579ebd.svg"></a>
<a title="Support me on Patreon :D" href="https://www.patreon.com/bePatron?u=7522179"><img src="https://img.shields.io/badge/patreon-support-%23f96854.svg"></a>
<a title="Follow me on Twitter" href="https://twitter.com/intent/user?screen_name=glutanimate"><img src="https://img.shields.io/twitter/follow/glutanimate.svg"></a>
</p>

> Flashcards from images – the easy way

*Image Occlusion Enhanced* is an add-on for the spaced repetition flashcard app [Anki](https://apps.ankiweb.net/) that allows you to create image-based cloze-deletions.

### Table of Contents <!-- omit in toc -->

<!-- MarkdownTOC levels="1,2,3" -->

- [Screenshots](#screenshots)
- [Installation](#installation)
- [Compared with Anki's built-in Image Occlusion](#compared-with-ankis-built-in-image-occlusion)
- [Converting notes](#converting-notes)
- [Documentation](#documentation)
- [Building](#building)
- [Contributing](#contributing)
- [License and Credits](#license-and-credits)

<!-- /MarkdownTOC -->

### Screenshots

*Creating Cards With the Add-on:*

<img src="screenshots/screenshot-io-editor-1.png">
<img src="screenshots/screenshot-io-editor-2.png">

*Reviewing Generated Cards:*

<img src="screenshots/screenshot-io-reviewer.png">

### Installation

#### From this repository's releases <!-- omit in toc -->

This version continues the original add-on with a reworked editor, new card types and tools, and fixes for current Anki releases; the [changelog](./CHANGELOG.md) lists them all. It runs on Anki 2.1.50 and later, and is tested on Anki 2.1.50, 23.12 and 26.09.

1. Download `image-occlusion-enhanced-<version>.ankiaddon` from the [latest release](https://github.com/Punnawit9285/image-occlusion-enhanced/releases/latest) (listed under *Assets*).
2. In Anki's main window, open *Tools* → *Add-ons*.
3. Drag the `.ankiaddon` file onto the add-ons list, or click *Install from file…* and choose it.
4. Restart Anki.

Already using Image Occlusion Enhanced from AnkiWeb? There is no need to remove it first: installing this package switches the AnkiWeb version off for you, and if both are ever enabled at once, the add-on offers to disable the older one. Your image occlusion notes, the note type and your settings are kept, because they live in your collection rather than in the add-on. To go back, enable the AnkiWeb version again under *Tools* → *Add-ons* and disable this one.

#### AnkiWeb <!-- omit in toc -->

The original v1.4.0 release from 2022 is still available on [AnkiWeb](https://ankiweb.net/shared/info/1374772155). It does not include the changes in this repository.

### Compared with Anki's built-in Image Occlusion

Anki has had its own Image Occlusion since version 23.10. Both make the same kind of card, and you can move notes from one to the other at any time (see below), so the choice is not final.

This add-on is the better fit if you want:

- **More fields**: Header, Footer, Remarks, Sources and two extra fields, with formatting and pictures, rather than just Header and Back Extra.
- **More drawing tools**: freehand shapes, paths, lines and arrows, coloured multi-line labels, layers, and grouping shapes into a single card.
- **Three card types**: *Hide All, Guess One* and *Hide One, Guess One* make a card per mask, and *Hide All, Guess All* makes a single card that asks about the whole image.
- **One note per card**, so each card shows up as its own row in the Browse window.
- **Mask Text**: one click finds the text labels in an image and covers each with a mask. It uses [Tesseract](https://tesseract-ocr.github.io) where installed, and otherwise the text recognition built into macOS and Windows.
- **Tap to reveal**: during review, tap any mask to uncover just that one, and tap again to cover it. Handy for checking neighbouring labels on the answer side.

Anki's built-in Image Occlusion is the better fit if you want:

- **Nothing to install**, and identical behaviour on every Anki app without relying on an add-on.
- **The fewest media files**: it draws its masks while you review, whereas this add-on saves a mask image for each card (cards of a *Hide One, Guess One* image share their answer image). Mask files that are no longer used are moved to Anki's media trash when you close your profile.

### Converting notes

On Anki 23.10 or later, select notes in the Browse window and choose *Notes* → *Image Occlusion* → *Convert to Anki's Image Occlusion...* or *Convert to Image Occlusion Enhanced...*.

- Scheduling and review history move to the new cards, and the original notes are deleted. Anki makes a backup first.
- An image is always converted as a whole: selecting one of its notes is enough.
- Lines, arrows and other drawings that Anki's built-in Image Occlusion cannot show are painted onto a copy of the image. Labels stay editable text.
- The conversion cannot be undone from the *Edit* menu, and your next sync has to upload the whole collection, just as when you change a note type in Anki.
- The mask files the old notes used are moved to Anki's media trash when you close your profile. *Tools* → *Check Media* can bring them back.

### Documentation

The installation and use of this add-on is detailed in the [Wiki](https://github.com/Glutanimate/image-occlusion-enhanced/wiki) and a [series of video tutorials on YouTube](https://www.youtube.com/playlist?list=PL3MozITKTz5YFHDGB19ypxcYfJ1ITk_6o). More information may also be found in the [AnkiWeb description](docs/description.md).

### Building

To build the `.ankiaddon` package yourself (needs only Python 3.9 or newer):

    git clone https://github.com/Punnawit9285/image-occlusion-enhanced.git
    cd image-occlusion-enhanced
    python3 tools/build_ankiaddon.py

Two packages are written to `build/`: one to install from a file, and one ending in `-ankiweb.ankiaddon` for uploading to AnkiWeb.

For development, link the source folder into Anki's add-ons folder instead, so that a restart of Anki picks up your changes. *Tools* → *Add-ons* → *View Files* opens that folder; on macOS it is `~/Library/Application Support/Anki2/addons21`:

    ln -s "$PWD/src/image_occlusion_enhanced" "$HOME/Library/Application Support/Anki2/addons21/image_occlusion_enhanced_2"

[CONTRIBUTING.md](./CONTRIBUTING.md) explains how to run the tests and how releases are made.

### Contributing

Contributions are welcome! Please review the [contribution guidelines](./CONTRIBUTING.md) on how to:

- Report issues
- File pull requests
- Support the project as a non-developer

### License and Credits

*Image Occlusion Enhanced* is

*Copyright © 2012-2015 [Tiago Barroso](https://github.com/tmbb)*

*Copyright © 2013 [Steve AW](https://github.com/steveaw)*

*Copyright © 2016-2022 [Aristotelis P.](https://glutanimate.com/) (Glutanimate)*

With code contributions from: Damien Elmes, Kyle Mills, James Kraus, Matt Restko

-----

*Image Occlusion Enhanced* is based on [Image Occlusion 2.0](https://github.com/tmbb/image-occlusion-2) by Tiago Barroso and [Simple Picture Occlusion](https://github.com/steveaw/anki_addons) by Steve AW. All credit for the original add-ons goes to their respective authors. *Image Occlusion Enhanced* would not exist without their work.

I would also like to extend my heartfelt thanks to everyone who has helped with testing, provided suggestions, or contributed in any other way.

*Image Occlusion Enhanced* ships with the following third-party open-source software:

- [SVG Edit](https://github.com/SVG-Edit/svgedit) 2.6. Copyright (c) 2009-2012 by SVG-edit authors. Licensed under the MIT license.

- `imghdr` from the [Python](https://www.python.org) standard library, which Python 3.13 no longer includes. Copyright (c) 2001-2018 Python Software Foundation. Licensed under the Python Software Foundation License (see `_vendor/PYTHON.LICENSE`).

- [imagesize.py](https://github.com/shibukawa/imagesize_py) v0.7.1. Copyright (c) 2016 Yoshiki Shibukawa. Licensed under the MIT license.

- [pathseg](https://github.com/progers/pathseg) 1.2.1. Copyright (c) 2015 The Chromium Authors. Licensed under a BSD-style license (see `svg-edit/editor/pathseg.js`).

Image Occlusion Enhanced is free and open-source software. The add-on code that runs within Anki is released under the GNU AGPLv3 license, extended by a number of additional terms. For more information please see the [LICENSE](https://github.com/glutanimate/image-occlusion-enhanced/blob/master/LICENSE) file that accompanied this program.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY.

----
<b>
<div align="center">The continued development of this add-on is made possible <br>thanks to my <a href="https://www.patreon.com/glutanimate">Patreon</a> and <a href="https://ko-fi.com/X8X0L4YV">Ko-Fi</a> supporters.
<br>You guys rock ❤️ !</div>
</b>