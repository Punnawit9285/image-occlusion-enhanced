from xml.dom import minidom

from conftest import DATA
from image_occlusion_enhanced import masks

SVG = (DATA / "sample-original-mask.svg").read_text()


def mask_indexes(svg):
    layer = masks.mask_layer(minidom.parseString(svg.encode()).documentElement)
    return [
        i
        for i, node in enumerate(layer.childNodes)
        if node.nodeType == node.ELEMENT_NODE and node.nodeName not in ("title", "text")
    ]


def shapes_in(svg):
    layer = masks.mask_layer(minidom.parseString(svg.encode()).documentElement)
    return [
        node
        for node in layer.childNodes
        if node.nodeType == node.ELEMENT_NODE and node.nodeName not in ("title", "text")
    ]


def labels_in(svg):
    return minidom.parseString(svg.encode()).getElementsByTagName("text").length


INDEXES = mask_indexes(SVG)


def test_sample_has_six_masks():
    assert len(INDEXES) == 6
    assert len(masks.mask_ids(SVG)) == 6


def test_hide_all_guess_one():
    target = INDEXES[2]
    q = shapes_in(masks.build_mask(SVG, "ao", "Q", INDEXES, target, "#FF0000"))
    assert len(q) == 6
    asked = [n for n in q if n.getAttribute("class") == "qshape"]
    assert len(asked) == 1 and asked[0].getAttribute("fill") == "#FF0000"
    a = shapes_in(masks.build_mask(SVG, "ao", "A", INDEXES, target, "#FF0000"))
    assert len(a) == 5
    assert all(n.getAttribute("class") != "qshape" for n in a)


def test_hide_one_guess_one():
    q = shapes_in(masks.build_mask(SVG, "oa", "Q", INDEXES, INDEXES[0], "#F00"))
    assert len(q) == 1 and q[0].getAttribute("class") == "qshape"
    a = masks.build_mask(SVG, "oa", "A", INDEXES, INDEXES[0], "#F00")
    assert shapes_in(a) == []
    # every card's answer is the same image
    assert a == masks.build_mask(SVG, "oa", "A", INDEXES, INDEXES[3], "#F00")


def test_hide_all_guess_all():
    q = shapes_in(masks.build_mask(SVG, "ag", "Q", INDEXES, None, "#F00"))
    assert len(q) == 6
    assert all(n.getAttribute("class") == "qshape" for n in q)
    # grouped shapes are recoloured too
    group = [n for n in q if n.nodeName == "g"][0]
    assert all(
        c.getAttribute("fill") == "#F00"
        for c in group.childNodes
        if c.nodeType == c.ELEMENT_NODE
    )
    assert shapes_in(masks.build_mask(SVG, "ag", "A", INDEXES, None, "#F00")) == []


def test_labels_stay_on_every_mask():
    for mode, target in (("ao", INDEXES[0]), ("oa", INDEXES[0]), ("ag", None)):
        for side in "QA":
            assert (
                labels_in(masks.build_mask(SVG, mode, side, INDEXES, target, "#F00"))
                == 2
            )


def test_note_id_pattern():
    match = masks.NOTE_ID_RE.match("0123abcd-ag-0")
    assert match and match.group("mode") == "ag" and match.group("nr") == "0"
    assert not masks.NOTE_ID_RE.match("svg_12")
