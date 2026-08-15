import numpy as np


class FrameDiffTrigger:
    """Detecteert beweging via frame-differencing op een grijswaarde-frame.

    Vervangbaar: een andere trigger-bron (PIR, detectiemodel) hoeft alleen
    dezelfde `.detect(frame_gray) -> bool`-interface te implementeren om
    deze klasse te vervangen, zonder de rest van de mirror-node aan te
    passen.
    """

    def __init__(self, threshold=25, min_changed_ratio=0.02):
        self._prev_gray = None
        self.threshold = threshold
        self.min_changed_ratio = min_changed_ratio

    def detect(self, frame_gray):
        if self._prev_gray is None:
            self._prev_gray = frame_gray
            return False

        diff = np.abs(frame_gray.astype(np.int16) - self._prev_gray.astype(np.int16))
        changed_ratio = np.mean(diff > self.threshold)
        self._prev_gray = frame_gray
        return bool(changed_ratio > self.min_changed_ratio)
