import cv2
import threading
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class CameraManager:
    def __init__(self):
        self.cameras: Dict[int, cv2.VideoCapture] = {}
        self.lock = threading.RLock()

    def add_camera(self, camera_id: int, url: str):
        """Add and initialize a camera"""
        with self.lock:
            if camera_id in self.cameras:
                self.cameras[camera_id].release()
            
            # Handle USB camera index vs RTSP URL
            try:
                if url.isdigit():
                    cap = cv2.VideoCapture(int(url))
                else:
                    cap = cv2.VideoCapture(url)
                
                if cap.isOpened():
                    self.cameras[camera_id] = cap
                    logger.info(f"Camera {camera_id} initialized: {url}")
                else:
                    logger.error(f"Failed to open camera {camera_id}: {url}")
            except Exception as e:
                logger.error(f"Error adding camera {camera_id}: {e}")

    def remove_camera(self, camera_id: int):
        """Remove and release a camera"""
        with self.lock:
            if camera_id in self.cameras:
                self.cameras[camera_id].release()
                del self.cameras[camera_id]
                logger.info(f"Camera {camera_id} released")

    def release_all(self):
        """Release all cameras"""
        with self.lock:
            for cap in self.cameras.values():
                cap.release()
            self.cameras.clear()
            logger.info("All cameras released")

    def capture_frame(self, camera_id: int):
        """Capture a single frame as a numpy array (RGB)"""
        with self.lock:
            # If requested camera is not active, try to find ANY working camera
            if camera_id not in self.cameras:
                # Try to auto-initialize index 0 first
                if camera_id == 0:
                    self.add_camera(0, "0")
                
                # If still not found (or if we want to be robust), check available indices
                if camera_id not in self.cameras:
                    logger.info("Requested camera not found. Scanning for available cameras...")
                    for i in range(5):
                        if i in self.cameras:
                            camera_id = i
                            break
                        # Try to init
                        self.add_camera(i, str(i))
                        if i in self.cameras:
                            camera_id = i
                            logger.info(f"Auto-discovered camera at index {i}")
                            break
            
            if camera_id not in self.cameras:
                return None
            
            cap = self.cameras[camera_id]
            ret, frame = cap.read()
            if ret:
                # Convert BGR to RGB for PIL
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return None

    def get_frame(self, camera_id: int) -> Optional[bytes]:
        """Get a frame encoded as JPEG bytes for streaming"""
        with self.lock:
            if camera_id not in self.cameras:
                # Try to auto-initialize if it's camera 0 (default)
                if camera_id == 0:
                    self.add_camera(0, "0")
                if camera_id not in self.cameras:
                    return None
            
            cap = self.cameras[camera_id]
            ret, frame = cap.read()
            if ret:
                _, buffer = cv2.imencode('.jpg', frame)
                return buffer.tobytes()
            return None

    def test_camera(self, url: str) -> bool:
        """Test if a camera URL is valid and accessible"""
        try:
            if url.isdigit():
                cap = cv2.VideoCapture(int(url))
            else:
                cap = cv2.VideoCapture(url)
            
            success = cap.isOpened()
            if success:
                # Try to read one frame to be sure
                ret, _ = cap.read()
                success = ret
            cap.release()
            return success
        except Exception as e:
            logger.error(f"Camera test failed for {url}: {e}")
            return False
