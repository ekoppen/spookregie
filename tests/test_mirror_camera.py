import os
from unittest.mock import patch, MagicMock
from mirror_node.camera import open_camera


def test_ffmpeg_capture_options_include_a_read_write_timeout():
    # Zonder rw_timeout kan een haperende netwerkstream (RTSP of, sinds de
    # HA-camera-proxy, ook http/mjpeg) cv2.VideoCapture()/cap.read() voor
    # altijd laten hangen en zo de hele render-loop bevriezen -- empirisch
    # bevestigd (5.2s met deze optie vs. >12s hang zonder, tegen een echte
    # stallende HTTP-server).
    #
    # 5s bleek echter zelf te krap: tegen een echte HA-camera-proxy-stream
    # (lan01, camera.lsc_smart_connect_1080p_ip_indoor_mini) kwam om de
    # paar frames een leesinterval van >5s voor (tot 5.7s gemeten), wat de
    # ffmpeg-mjpeg-demuxer op een timeout liet stukgaan ("overread") --
    # daarna faalden ALLE volgende reads meteen, blijvend, tot een reopen.
    # 15s gaf in dezelfde herhaalde test ruim marge (max ~5.7s per frame),
    # geen enkele mislukte read meer. Deze test bewaakt alleen dat de optie
    # blijft staan, niet het timinggedrag zelf (dat vereist een echte server).
    assert "rw_timeout;15000000" in os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]


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
