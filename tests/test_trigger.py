import numpy as np
from mirror_node.trigger import FrameDiffTrigger


def test_first_frame_never_triggers():
    trigger = FrameDiffTrigger()
    frame = np.zeros((10, 10), dtype=np.uint8)
    assert trigger.detect(frame) is False


def test_identical_frames_do_not_trigger():
    trigger = FrameDiffTrigger()
    frame = np.zeros((10, 10), dtype=np.uint8)
    trigger.detect(frame)
    assert trigger.detect(frame) is False


def test_large_change_triggers():
    trigger = FrameDiffTrigger(threshold=25, min_changed_ratio=0.02)
    frame1 = np.zeros((10, 10), dtype=np.uint8)
    trigger.detect(frame1)

    frame2 = np.full((10, 10), 255, dtype=np.uint8)
    assert trigger.detect(frame2) is True


def test_tiny_change_does_not_trigger():
    trigger = FrameDiffTrigger(threshold=25, min_changed_ratio=0.5)
    frame1 = np.zeros((10, 10), dtype=np.uint8)
    trigger.detect(frame1)

    frame2 = np.zeros((10, 10), dtype=np.uint8)
    frame2[0, 0] = 255  # 1 van de 100 pixels = 1%
    assert trigger.detect(frame2) is False
