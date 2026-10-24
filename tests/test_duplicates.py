from image_occlusion_enhanced import duplicates as d

ANKIWEB_OLD = ("1374772155", "Image Occlusion Enhanced", (1, 4, 0))
GITHUB = ("image_occlusion_enhanced_2", "Image Occlusion Enhanced", (2, 1, 0))
ANKIWEB_NEW = ("2093847561", "Image Occlusion Enhanced (Continued)", (2, 1, 0))


def test_parse_version():
    assert d.parse_version('__version__ = "v2.1.0"') == (2, 1, 0)
    assert d.parse_version("nothing") == ()


def test_recognises_copies():
    assert d.is_copy("1374772155", "whatever")
    assert d.is_copy("123", "Image Occlusion Enhanced (Continued)")
    assert not d.is_copy("123", "Image Occlusion")  # Anki's own is not an add-on


def test_newest_copy_stays():
    assert d.keeper([ANKIWEB_OLD, GITHUB]) == GITHUB[0]
    assert d.to_disable(GITHUB, [ANKIWEB_OLD]) == [ANKIWEB_OLD]
    assert d.to_disable(ANKIWEB_OLD, [GITHUB]) == []


def test_ankiweb_copy_stays_on_a_tie():
    assert d.keeper([GITHUB, ANKIWEB_NEW]) == ANKIWEB_NEW[0]
    assert d.to_disable(ANKIWEB_NEW, [GITHUB, ANKIWEB_OLD]) == [GITHUB, ANKIWEB_OLD]
    assert d.to_disable(GITHUB, [ANKIWEB_NEW]) == []


def test_exactly_one_copy_asks():
    copies = [ANKIWEB_OLD, GITHUB, ANKIWEB_NEW]
    asking = [c for c in copies if d.to_disable(c, [o for o in copies if o != c])]
    assert asking == [ANKIWEB_NEW]


def test_alone_nothing_to_do():
    assert d.to_disable(GITHUB, []) == []
