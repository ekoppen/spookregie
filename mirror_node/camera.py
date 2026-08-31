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
