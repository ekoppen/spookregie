import numpy as np
from mirror_node.overlay import composite_overlay


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
