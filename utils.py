import io
import os
import time
import logging
from PIL import Image

logger = logging.getLogger(__name__)

def convert_image_to_bytes(image: Image.Image, format: str = "PNG") -> bytes:
    """Convert PIL image to bytes"""
    buf = io.BytesIO()
    image.save(buf, format=format)
    return buf.getvalue()

def cleanup_old_files(directory: str = "/tmp", max_age_seconds: int = 3600):
    """Cleanup temporary files older than max_age_seconds"""
    try:
        now = time.time()
        for f in os.listdir(directory):
            path = os.path.join(directory, f)
            if os.path.isfile(path):
                if os.stat(path).st_mtime < now - max_age_seconds:
                    if f.startswith("temp_"):
                        os.remove(path)
                        logger.info(f"Cleaned up old temp file: {f}")
    except Exception as e:
        logger.error(f"Cleanup error in {directory}: {e}")