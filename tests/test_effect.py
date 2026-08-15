import numpy as np
from mirror_node.effect import ghost_effect


def test_output_shape_and_dtype_match_input():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    result = ghost_effect(frame)
    assert result.shape == frame.shape
    assert result.dtype == np.uint8


def test_white_input_becomes_dark():
    frame = np.full((20, 20, 3), 255, dtype=np.uint8)
    result = ghost_effect(frame)
    assert result.mean() < frame.mean()
