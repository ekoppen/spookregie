import os
os.environ.setdefault(
    # stimeout bindt alleen RTSP; rw_timeout is FFmpeg's generieke
    # protocol-brede leestimeout (ook http/mjpeg, zoals de HA-camera-proxy)
    # -- zonder deze kon een haperende netwerkstream cv2.VideoCapture()
    # zelf, of een latere cap.read(), voor altijd laten hangen en zo de
    # hele (single-threaded) render-loop muisstil bevriezen. Onbekende
    # optie voor een protocol -> FFmpeg negeert 'm met een warning, geen
    # crash (zelfde bewezen-veilig patroon als stimeout nu al gebruikt).
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000|rw_timeout;5000000"
)

import cv2


def open_camera(source, camera_index=0):
    """Opent de camera-bron: leeg -> lokale index (camera_index), een
    numerieke string -> die index, anders -> een netwerkstream via
    FFmpeg. Camera-merk-agnostisch: elke bron die OpenCV/FFmpeg begrijpt
    werkt. Verplaatst uit mirror_node/main.py zodat de admin-backend 'm
    ook kan gebruiken voor het losse voorbeeldpaneel (zonder de fysieke
    spiegel aan te raken)."""
    if not source:
        return cv2.VideoCapture(camera_index)
    try:
        return cv2.VideoCapture(int(source))
    except ValueError:
        return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
