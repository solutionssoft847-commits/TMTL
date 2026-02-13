import cv2
import time
import threading
import logging
from typing import List, Optional, Dict, Union

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CameraManager:
    def __init__(self):
        self.cameras: Dict[int, cv2.VideoCapture] = {}
        self.lock = threading.Lock()
        self.active_camera_id: Optional[int] = None
    
    def get_available_cameras(self, max_check: int = 5) -> List[int]:
        """
        Scans for available cameras by attempting to open indices 0 to max_check.
        Returns a list of available camera indices.
        """
        available_cameras = []
        for i in range(max_check):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) # CAP_DSHOW for faster checking on Windows
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    available_cameras.append(i)
                cap.release()
            else:
                # On some systems, if 0 and 1 exist, checking 2 might fail fast.
                pass
        
        logger.info(f"Auto-detected cameras: {available_cameras}")
        return available_cameras
    
    def start_camera(self, camera_id: int) -> bool:
        """
        Initializes a camera if not already active.
        Closes other cameras to save resources (single active camera policy).
        """
        with self.lock:
            # If requesting the already active camera, just return True
            if self.active_camera_id == camera_id and camera_id in self.cameras:
                if self.cameras[camera_id].isOpened():
                    return True
            
            # Close existing camera if switching
            if self.active_camera_id is not None and self.active_camera_id in self.cameras:
                self.release_camera(self.active_camera_id)
            
            # Start new camera
            cap = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
            if cap.isOpened():
                # Set common resolution (can be made configurable)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                
                self.cameras[camera_id] = cap
                self.active_camera_id = camera_id
                logger.info(f"Started camera {camera_id}")
                return True
            else:
                logger.error(f"Failed to open camera {camera_id}")
                return False
    
    def get_frame(self, camera_id: int) -> Optional[bytes]:
        """
        Captures a frame from the specified camera and returns it as JPEG bytes.
        Ideal for video streaming.
        """
        # Ensure camera is started
        if self.active_camera_id != camera_id or camera_id not in self.cameras:
            if not self.start_camera(camera_id):
                return None
        
        cap = self.cameras.get(camera_id)
        if cap and cap.isOpened():
            ret, frame = cap.read()
            if ret:
                try:
                    # Encode to JPEG
                    ret, buffer = cv2.imencode('.jpg', frame)
                    if ret:
                        return buffer.tobytes()
                except Exception as e:
                    logger.error(f"Error encoding frame: {e}")
            else:
                logger.warning(f"Failed to read frame from camera {camera_id}")
        return None

    def capture_frame(self, camera_id: int) -> Optional[object]:
        """
        Captures a frame and returns it as a PIL Image.
        Ideal for processing/inference.
        """
        from PIL import Image
        
        # Ensure camera is started
        if self.active_camera_id != camera_id or camera_id not in self.cameras:
            if not self.start_camera(camera_id):
                return None
                
        cap = self.cameras.get(camera_id)
        if cap and cap.isOpened():
            ret, frame = cap.read()
            if ret:
                # Convert BGR (OpenCV) to RGB (PIL)
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                return Image.fromarray(frame_rgb)
        return None

    def release_camera(self, camera_id: int):
        """Releases a specific camera resource."""
        with self.lock:
            if camera_id in self.cameras:
                self.cameras[camera_id].release()
                del self.cameras[camera_id]
                if self.active_camera_id == camera_id:
                    self.active_camera_id = None
                logger.info(f"Released camera {camera_id}")

    def release_all(self):
        """Releases all camera resources."""
        with self.lock:
            for cam_id, cap in self.cameras.items():
                cap.release()
            self.cameras.clear()
            self.active_camera_id = None
            logger.info("Released all cameras")
