from image_occlusion_enhanced import tapreveal

BEGIN = tapreveal.TAP_TO_REVEAL_BEGIN % tapreveal.TAP_TO_REVEAL_VERSION


def test_adds_script_once():
    once = tapreveal.with_tap_to_reveal("{{Image}}\n<div>custom</div>")
    assert once.count(BEGIN) == 1
    assert once.startswith("{{Image}}\n<div>custom</div>")
    assert tapreveal.with_tap_to_reveal(once) == once


def test_replaces_older_version_in_place():
    old = (
        "{{Image}}\n\n<!-- Image Occlusion Enhanced: tap to reveal (v0) -->\n"
        "<script>old()</script>\n<!-- /Image Occlusion Enhanced: tap to reveal -->\n"
        "<div>after</div>"
    )
    new = tapreveal.with_tap_to_reveal(old)
    assert "old()" not in new
    assert new.count(BEGIN) == 1
    assert "<div>after</div>" in new
    assert new.index("<div>after</div>") < new.index(BEGIN)


def test_script_is_self_contained():
    script = tapreveal.tap_to_reveal_script
    assert script.startswith("<script>") and script.endswith("</script>")
    # wrapped in a function, so cards do not leak variables into each other
    assert "(function () {" in script
    assert "\\\\s" not in script and "\\s+" in script
