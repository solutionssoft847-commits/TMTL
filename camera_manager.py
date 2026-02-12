import cv2
import threading
import logging
import time
import os
from datetime import datetime
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
                    if os.getenv("RENDER") or os.getenv("K_SERVICE") or os.getenv("SPACE_ID"):
                        logger.warning(f"Could not open camera {camera_id} ({url}) in cloud environment. This is expected.")
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
            # If requested camera is already open, use it
            if camera_id in self.cameras:
                cap = self.cameras[camera_id]
                ret, frame = cap.read()
                if ret:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # If we are in the cloud, provided a simulated frame instead of None
            if os.getenv("RENDER") or os.getenv("K_SERVICE") or os.getenv("SPACE_ID"):
                import numpy as np
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "SIMULATED CAPTURE", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                # Show timestamp to make it unique
                cv2.putText(frame, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (150, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Non-cloud auto-discovery logic
            if camera_id not in self.cameras:
                if camera_id == 0:
                    self.add_camera(0, "0")
                
                if camera_id not in self.cameras:
                    logger.info("Scanning for available cameras...")
                    for i in range(5):
                        if i in self.cameras:
                            camera_id = i; break
                        if i == 0 and 0 not in self.cameras: continue
                        self.add_camera(i, str(i))
                        if i in self.cameras:
                            camera_id = i; break
            
            if camera_id in self.cameras:
                cap = self.cameras[camera_id]
                ret, frame = cap.read()
                if ret:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return None

    def get_frame(self, camera_id: int) -> Optional[bytes]:
        """Get a frame encoded as JPEG bytes for streaming"""
        with self.lock:
            # Try to get real frame first
            if camera_id in self.cameras:
                cap = self.cameras[camera_id]
                ret, frame = cap.read()
                if ret:
                    _, buffer = cv2.imencode('.jpg', frame)
                    return buffer.tobytes()

            # If no real camera, check if we should show a simulator/placeholder
            if os.getenv("RENDER") or os.getenv("K_SERVICE") or os.getenv("SPACE_ID"):
                import numpy as np
                # Generate a "Simulator" frame
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "CAMERA SIMULATOR ACTIVE", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.putText(frame, f"SOURCE: {camera_id}", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
                cv2.putText(frame, "Local hardware unavailable on cloud server", (50, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
                
                # Add a moving "scan line"
                t = int(time.time() * 50) % 480
                cv2.line(frame, (0, t), (640, t), (0, 255, 255), 1)
                
                _, buffer = cv2.imencode('.jpg', frame)
                return buffer.tobytes()

            # Final attempt to auto-init index 0 for non-cloud
            if camera_id not in self.cameras and camera_id == 0:
                self.add_camera(0, "0")
                if 0 in self.cameras:
                    cap = self.cameras[0]
                    ret, frame = cap.read()
                    if ret:
                        _, buffer = cv2.imencode('.jpg', frame)
                        return buffer.tobytes()

            return None

    def test_camera(self, url: str) -> bool:
        """Test if a camera URL is valid and accessible"""
        # Skip hardware check on cloud environments for local-only URLs
        if os.getenv("RENDER") or os.getenv("K_SERVICE") or os.getenv("SPACE_ID"):
            if url.isdigit() or "localhost" in url or "127.0.0.1" in url:
                logger.warning(f"Cloud environment detected. Permitting local camera URL '{url}' without hardware test.")
                return True

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
