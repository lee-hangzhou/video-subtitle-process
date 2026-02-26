import os

from app.vars.constants import HARDCODE_VIDEO_FORMATS, ALLOWED_SUBTITLE_FORMATS


def video_validation(video_path: str) -> bool:
    ext = os.path.splitext(video_path)[1].lower()
    return ext in HARDCODE_VIDEO_FORMATS


def subtitle_validation(subtitle_path: str) -> bool:
    ext = os.path.splitext(subtitle_path)[1].lower()
    return ext in ALLOWED_SUBTITLE_FORMATS
