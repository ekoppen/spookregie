import numpy as np


def posterize(frame_bgr, params):
    """params: {"levels": int >= 2, standaard 4}."""
    levels = max(2, int(params.get("levels", 4)))
    step = 256 // levels
    return ((frame_bgr.astype(np.int32) // step) * step).astype(np.uint8)
