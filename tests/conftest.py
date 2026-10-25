"""
Test setup.

The add-on's __init__.py starts the add-on inside a running Anki, so the
package is registered here without running it. Modules that do not import
aqt can then be imported and tested as image_occlusion_enhanced.<module>.
"""

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = "image_occlusion_enhanced"
DATA = pathlib.Path(__file__).resolve().parent / "data"

if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT / "src" / PACKAGE)]
    sys.modules[PACKAGE] = package
