from unittest.mock import patch, MagicMock
from mirror_node.camera import open_camera


def test_empty_source_opens_local_index():
    with patch("mirror_node.camera.cv2") as mock_cv2:
        mock_cv2.VideoCapture = MagicMock()
        open_camera("", camera_index=2)
        mock_cv2.VideoCapture.assert_called_once_with(2)


def test_numeric_string_source_opens_that_index():
    with patch("mirror_node.camera.cv2") as mock_cv2:
        mock_cv2.VideoCapture = MagicMock()
        open_camera("3", camera_index=0)
        mock_cv2.VideoCapture.assert_called_once_with(3)


def test_url_source_opens_via_ffmpeg():
    with patch("mirror_node.camera.cv2") as mock_cv2:
        mock_cv2.VideoCapture = MagicMock()
        mock_cv2.CAP_FFMPEG = "FFMPEG_SENTINEL"
        open_camera("rtsp://cam.local/stream", camera_index=0)
        mock_cv2.VideoCapture.assert_called_once_with("rtsp://cam.local/stream", "FFMPEG_SENTINEL")
