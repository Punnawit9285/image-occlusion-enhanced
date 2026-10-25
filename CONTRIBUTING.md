## How to Contribute to this Project

Bug reports, ideas and pull requests are welcome in this repository's [issue tracker](https://github.com/Punnawit9285/image-occlusion-enhanced/issues). Please mention your Anki version and operating system, and for problems with particular cards, how they were made.

### Development

Link `src/image_occlusion_enhanced` into Anki's add-ons folder (see *Building* in the README) and restart Anki to load your changes.

The tests need Python 3.10 or newer, for the `anki` package they install, but no Anki installation. The add-on itself still has to run on Python 3.9, as used by Anki 2.1.50, which one of the tests checks:

    python3 -m pip install -r requirements-dev.txt
    ruff check src tools tests
    python3 -m pytest

Two tests are skipped unless their tools are installed: Tesseract for text recognition, and Node.js with [Playwright](https://playwright.dev) (`npm install --no-save playwright && npx playwright install chromium`) for the review-time script. GitHub runs everything, including those, for every push and pull request.

Most of the code that runs inside Anki can only be checked there. Please try a change in Anki before opening a pull request, and say which version you used.

### Releases

The version number lives in `src/image_occlusion_enhanced/_version.py`; `pyproject.toml` must agree, and `CHANGELOG.md` needs an entry for it. Pushing a tag such as `v2.1.0` then tests and builds the add-on and publishes a GitHub release with the package attached and the changelog entry as its notes. The workflow refuses to publish if the tag and the version files disagree.

The release carries two packages. `image-occlusion-enhanced-<version>.ankiaddon` is for installing from GitHub. `image-occlusion-enhanced-<version>-ankiweb.ankiaddon` is the one to upload to AnkiWeb: it is the same add-on, but installing it from AnkiWeb also switches off a copy installed from GitHub. After the first upload, enter the AnkiWeb ID as `ANKIWEB_ID` in `tools/build_ankiaddon.py`, so that the GitHub package does the same the other way round.
