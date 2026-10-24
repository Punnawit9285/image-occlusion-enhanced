from image_occlusion_enhanced import geometry as g


def close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_parse_transform_composes_left_to_right():
    m = g.parse_transform("translate(10 20) scale(2)")
    assert close(g.apply(m, (1, 1)), (12, 22))


def test_rotate_about_point():
    m = g.parse_transform("rotate(90 10 10)")
    assert close(g.apply(m, (20, 10)), (10, 20))


def test_matrix_and_skew():
    m = g.parse_transform("matrix(1,0,0,1,5,6)")
    assert close(g.apply(m, (0, 0)), (5, 6))
    skew = g.parse_transform("skewX(45)")
    assert close(g.apply(skew, (0, 10)), (10, 10))
    assert not g.is_axis_aligned(skew)


def test_unreadable_transform_is_identity():
    assert g.parse_transform("bogus(1)") == g.IDENTITY
    assert g.parse_transform(None) == g.IDENTITY


def test_axis_aligned():
    assert g.is_axis_aligned(g.parse_transform("translate(3) scale(-1, 2)"))
    assert not g.is_axis_aligned(g.parse_transform("rotate(10)"))


def test_flatten_lines_and_close():
    paths = g.flatten_path("M 0 0 L 10 0 L 10 10 Z M 20 20 h 5 v 5")
    assert paths[0] == [(0, 0), (10, 0), (10, 10)]
    assert paths[1] == [(20, 20), (25, 20), (25, 25)]


def test_flatten_implicit_lineto_and_relative():
    paths = g.flatten_path("m 1 1 2 0 0 2")
    assert paths == [[(1, 1), (3, 1), (3, 3)]]


def test_flatten_cubic_ends_on_end_point():
    (path,) = g.flatten_path("M0 0 C 0 10 10 10 10 0", curve_steps=8)
    assert len(path) == 9
    assert close(path[-1], (10, 0))
    # the curve bulges towards the control points
    assert max(p[1] for p in path) > 5


def test_flatten_smooth_and_quadratic():
    (path,) = g.flatten_path("M0 0 Q 5 10 10 0 T 20 0", curve_steps=4)
    assert close(path[-1], (20, 0))
    assert min(p[1] for p in path) < -1  # the reflected control point


def test_flatten_arc_packed_flags():
    (path,) = g.flatten_path("M0 0 a5 5 0 01 10 0", curve_steps=8)
    assert close(path[-1], (10, 0))
    # sweep flag 1: a half circle below the chord in SVG's y-down coordinates
    xs = [p[0] for p in path]
    assert min(xs) >= -1e-6 and max(xs) <= 10 + 1e-6
    assert close((max(abs(p[1]) for p in path),), (5,), tol=0.2)


def test_flatten_malformed_keeps_what_was_read():
    paths = g.flatten_path("M 0 0 L 10 0 L 10 10 L oops")
    assert paths == [[(0, 0), (10, 0), (10, 10)]]


def test_simplify_drops_collinear_points():
    points = [(float(i), 0.0) for i in range(100)] + [(99.0, 50.0)]
    assert g.simplify(points, 0.5) == [(0.0, 0.0), (99.0, 0.0), (99.0, 50.0)]


def test_simplify_to_limits_points():
    circle = g.ellipse_points(0, 0, 100, 100, segments=1000)
    result = g.simplify_to(circle, 0.01, 50)
    assert 3 <= len(result) <= 50


def test_parse_points():
    assert g.parse_points("1,2 3,4  5 6") == [(1, 2), (3, 4), (5, 6)]
