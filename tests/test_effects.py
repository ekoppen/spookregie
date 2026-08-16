import numpy as np
from mirror_node.effects import EFFECTS, get_effect


def _sample_frame():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    frame[5:15, 5:15] = (200, 100, 50)
    return frame


def test_registry_contains_all_four_effects():
    assert set(EFFECTS.keys()) == {"xray", "thermal", "contour", "posterize"}


def test_get_effect_returns_callable_for_known_name():
    fn = get_effect("xray")
    assert callable(fn)


def test_get_effect_raises_for_unknown_name():
    try:
        get_effect("nonexistent")
        assert False, "had een ValueError moeten geven"
    except ValueError:
        pass


def test_all_effects_preserve_shape_and_dtype():
    frame = _sample_frame()
    for name, fn in EFFECTS.items():
        result = fn(frame, {})
        assert result.shape == frame.shape, f"{name} veranderde de shape"
        assert result.dtype == np.uint8, f"{name} veranderde het dtype"


def test_xray_intensity_zero_differs_from_intensity_one():
    frame = _sample_frame()
    low = EFFECTS["xray"](frame, {"intensity": 0.0})
    high = EFFECTS["xray"](frame, {"intensity": 1.0})
    assert not np.array_equal(low, high)


def test_thermal_intensity_zero_differs_from_intensity_one():
    frame = _sample_frame()
    low = EFFECTS["thermal"](frame, {"intensity": 0.0})
    high = EFFECTS["thermal"](frame, {"intensity": 1.0})
    assert not np.array_equal(low, high)


def test_posterize_reduces_unique_values():
    frame = _sample_frame()
    result = EFFECTS["posterize"](frame, {"levels": 2})
    assert len(np.unique(result)) <= len(np.unique(frame))


def test_contour_output_is_edges_on_black():
    # Een egaal frame heeft geen randen -> praktisch zwart resultaat.
    flat_frame = np.full((20, 20, 3), 128, dtype=np.uint8)
    result = EFFECTS["contour"](flat_frame, {})
    assert result.mean() < 5
