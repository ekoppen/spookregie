import numpy as np
from mirror_node.overlay import composite_overlay, place_on_canvas


def test_fully_opaque_overlay_covers_center():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    overlay = np.zeros((20, 20, 4), dtype=np.uint8)
    overlay[:, :, :3] = (10, 20, 30)  # BGR
    overlay[:, :, 3] = 255  # volledig ondoorzichtig

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.5, 0.5))

    center_pixel = result[50, 50]
    assert tuple(center_pixel) == (10, 20, 30)
    # buiten de overlay blijft het frame ongewijzigd
    assert tuple(result[0, 0]) == (0, 0, 0)


def test_fully_transparent_overlay_leaves_frame_unchanged():
    frame = np.full((50, 50, 3), 100, dtype=np.uint8)
    overlay = np.zeros((10, 10, 4), dtype=np.uint8)
    overlay[:, :, :3] = 255
    overlay[:, :, 3] = 0  # volledig doorzichtig

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.5, 0.5))

    assert np.array_equal(result, frame)


def test_original_frame_is_not_mutated():
    frame = np.zeros((30, 30, 3), dtype=np.uint8)
    overlay = np.full((10, 10, 4), 255, dtype=np.uint8)

    composite_overlay(frame, overlay)

    assert np.array_equal(frame, np.zeros((30, 30, 3), dtype=np.uint8))


def test_overlay_partially_outside_frame_does_not_crash():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    overlay = np.full((10, 10, 4), 255, dtype=np.uint8)

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.0, 0.0))

    assert result.shape == frame.shape


def test_overlay_larger_than_frame_does_not_crash():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    overlay = np.full((50, 50, 4), 255, dtype=np.uint8)

    result = composite_overlay(frame, overlay, scale=1.0, position=(0.5, 0.5))

    assert result.shape == frame.shape


def test_place_on_canvas_centers_smaller_frame_with_black_borders():
    frame = np.full((20, 20, 3), 200, dtype=np.uint8)

    result = place_on_canvas(frame, (40, 40), scale=1.0, position=(0.5, 0.5))

    assert result.shape == (40, 40, 3)
    assert tuple(result[20, 20]) == (200, 200, 200)  # midden = het frame
    assert tuple(result[0, 0]) == (0, 0, 0)  # rand = zwarte letterbox


def test_place_on_canvas_scale_shrinks_frame():
    frame = np.full((40, 40, 3), 200, dtype=np.uint8)

    result = place_on_canvas(frame, (40, 40), scale=0.5, position=(0.5, 0.5))

    # bij 0.5x is het geschaalde frame 20x20, gecentreerd -> randen zwart
    assert tuple(result[0, 0]) == (0, 0, 0)
    assert tuple(result[20, 20]) == (200, 200, 200)


def test_place_on_canvas_position_moves_frame_to_corner():
    frame = np.full((10, 10, 3), 200, dtype=np.uint8)

    result = place_on_canvas(frame, (40, 40), scale=1.0, position=(0.0, 0.0))

    assert tuple(result[0, 0]) == (200, 200, 200)
    assert tuple(result[39, 39]) == (0, 0, 0)


def test_place_on_canvas_does_not_mutate_original_frame():
    frame = np.full((20, 20, 3), 200, dtype=np.uint8)

    place_on_canvas(frame, (40, 40), scale=1.0, position=(0.5, 0.5))

    assert np.array_equal(frame, np.full((20, 20, 3), 200, dtype=np.uint8))


def test_place_on_canvas_frame_larger_than_canvas_does_not_crash():
    frame = np.full((80, 80, 3), 200, dtype=np.uint8)

    result = place_on_canvas(frame, (40, 40), scale=1.0, position=(0.5, 0.5))

    assert result.shape == (40, 40, 3)
