import shutil

import pytest

from conftest import DATA
from image_occlusion_enhanced import ocr

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t800\t600\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t43\t288\t92\t23\t95.1\tFemur\n"
    "5\t1\t2\t1\t1\t1\t563\t427\t95\t24\t91.0\tPatella\n"
    "5\t1\t2\t1\t1\t2\t672\t427\t71\t24\t90.2\tbone\n"
    "5\t1\t3\t1\t1\t1\t300\t100\t20\t20\t12.0\tnoise\n"
    "5\t1\t4\t1\t1\t1\t10\t10\t8\t20\t96.0\t|\n"
)


def test_parse_tesseract_tsv():
    words = ocr.parse_tesseract_tsv(TSV)
    assert [w.text for w in words] == ["Femur", "Patella", "bone", "|"]
    assert words[1].line == words[2].line != words[0].line


def test_parse_rejects_other_formats():
    with pytest.raises(ocr.OcrError):
        ocr.parse_tesseract_tsv("something else\n1 2 3")


def test_words_on_a_line_form_one_label():
    boxes = ocr.group_labels(ocr.parse_tesseract_tsv(TSV), 800, 600)
    # "|" carries no letters or digits, "noise" is below the confidence limit
    assert len(boxes) == 2
    left, top, width, height = boxes[1]
    assert left < 563 and left + width > 743 and top < 427 and top + height > 451


def test_distant_words_on_a_line_are_separate_labels():
    words = [
        ocr.Word("Aorta", 10, 10, 60, 20, "line"),
        ocr.Word("Vein", 400, 10, 50, 20, "line"),
    ]
    assert len(ocr.group_labels(words, 800, 600)) == 2


def test_stacked_lines_form_one_label():
    words = [
        ocr.Word("Superior", 100, 100, 90, 20, 1),
        ocr.Word("vena", 110, 124, 50, 20, 2),
        ocr.Word("cava", 165, 124, 50, 20, 2),
        ocr.Word("Far", 100, 400, 40, 20, 3),
    ]
    boxes = ocr.group_labels(words, 800, 600)
    assert len(boxes) == 2
    assert boxes[0][3] > 40  # spans both lines


def test_boxes_stay_inside_the_image_and_skip_pages_of_text():
    words = [ocr.Word("Edge", 0, 0, 50, 20, 1), ocr.Word("Page", 0, 0, 790, 590, 2)]
    boxes = ocr.group_labels(words, 800, 600)
    assert boxes == [(0.0, 0.0, 54.0, 24.0)]


def test_parse_vision_output_flips_y():
    words = ocr.parse_vision_output('[["Tibia", 0.5, 0.75, 0.25, 0.05]]', 800, 600)
    (word,) = words
    assert (word.text, word.left, word.width) == ("Tibia", 400, 200)
    assert abs(word.top - 120) < 1e-6 and abs(word.height - 30) < 1e-6


def test_parse_windows_output():
    output = "0\t10\t20\t30\t12\tLeft\n0\t45,5\t20\t30\t12\tlung\nbad line\n"
    words = ocr.parse_windows_output(output)
    assert [(w.text, w.left, w.line) for w in words] == [
        ("Left", 10.0, ("windows", 0)),
        ("lung", 45.5, ("windows", 0)),
    ]


def test_configured_tesseract_must_exist(tmp_path):
    assert ocr.find_tesseract(str(tmp_path / "missing")) is None
    program = tmp_path / "tesseract"
    program.write_text("")
    assert ocr.find_tesseract(str(program)) == str(program)


@pytest.mark.skipif(not shutil.which("tesseract"), reason="needs Tesseract")
def test_finds_the_labels_of_a_diagram():
    engine = ocr.available_engine()
    boxes = ocr.find_labels(engine, str(DATA / "sample-labels.png"), 800, 600)
    # Femur, Tibia, "Patella bone" and Fibula
    assert len(boxes) == 4
    centres = sorted((round(l + w / 2), round(t + h / 2)) for l, t, w, h in boxes)
    expected = sorted([(88, 300), (697, 159), (653, 439), (104, 509)])
    for (x, y), (ex, ey) in zip(centres, expected):
        assert abs(x - ex) < 15 and abs(y - ey) < 10
