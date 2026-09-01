import logging
from unittest.mock import MagicMock

from mirror_node.camera_server import read_frame_with_reopen


def test_read_frame_with_reopen_returns_frame_on_success():
    cap = MagicMock()
    cap.read.return_value = (True, "FRAME")
    logger = logging.getLogger("test-camera-server")

    frame, new_cap, failures = read_frame_with_reopen(cap, "0", 0, logger)

    assert frame == "FRAME"
    assert new_cap is cap
    assert failures == 0


def test_read_frame_with_reopen_counts_failures_without_reopening():
    cap = MagicMock()
    cap.read.return_value = (False, None)
    logger = logging.getLogger("test-camera-server")

    frame, new_cap, failures = read_frame_with_reopen(cap, "0", 5, logger, max_failures=30)

    assert frame is None
    assert new_cap is cap
    assert failures == 6
    cap.release.assert_not_called()


def test_read_frame_with_reopen_reopens_after_max_failures(monkeypatch):
    import mirror_node.camera_server as camera_server_module

    cap = MagicMock()
    cap.read.return_value = (False, None)
    reopened_cap = MagicMock()
    monkeypatch.setattr(camera_server_module, "open_camera", lambda source: reopened_cap)
    logger = logging.getLogger("test-camera-server")

    frame, new_cap, failures = read_frame_with_reopen(cap, "0", 29, logger, max_failures=30)

    assert frame is None
    assert new_cap is reopened_cap
    assert failures == 0
    cap.release.assert_called_once()
