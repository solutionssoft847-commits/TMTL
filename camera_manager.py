import cv2
import threading
import logging
import time
import os
import numpy as np
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from collections import deque
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    """Camera configuration settings for industrial use"""
    resolution: Tuple[int, int] = (1920, 1080)  # Full HD default
    fps: int = 30
    exposure: Optional[int] = None  # Auto exposure if None
    gain: Optional[float] = None
    white_balance: Optional[int] = None
    focus: Optional[int] = None
    brightness: Optional[int] = None
    contrast: Optional[int] = None
    saturation: Optional[int] = None
    buffer_size: int = 5  # Number of frames to buffer
    warmup_frames: int = 30  # Frames to skip during initialization
    timeout: int = 5  # Connection timeout in seconds
    retry_attempts: int = 3
    retry_delay: float = 2.0


@dataclass
class FrameQuality:
    """Frame quality metrics"""
    brightness: float
    sharpness: float
    contrast: float
    noise_level: float
    is_blurred: bool
    is_overexposed: bool
    is_underexposed: bool
    quality_score: float  # 0-100


class CameraMetrics:
    """Track camera performance metrics"""

    def __init__(self):
        self.total_frames = 0
        self.failed_frames = 0
        self.avg_capture_time = 0.0
        self.last_capture_time = 0.0
        self.quality_scores = deque(maxlen=100)
        self.connection_failures = 0
        self.last_error = None
        self.last_success = None

    def record_capture(self, success: bool, capture_time: float, quality_score: float = 0):
        """Record capture metrics"""
        self.total_frames += 1
        if success:
            self.last_capture_time = capture_time
            self.avg_capture_time = (self.avg_capture_time * 0.9) + (capture_time * 0.1)
            self.quality_scores.append(quality_score)
            self.last_success = datetime.now()
        else:
            self.failed_frames += 1

    def get_stats(self) -> dict:
        """Get camera statistics"""
        success_rate = ((self.total_frames - self.failed_frames) / self.total_frames * 100) if self.total_frames > 0 else 0
        avg_quality = sum(self.quality_scores) / len(self.quality_scores) if self.quality_scores else 0

        return {
            "total_frames": self.total_frames,
            "failed_frames": self.failed_frames,
            "success_rate": round(success_rate, 2),
            "avg_capture_time_ms": round(self.avg_capture_time * 1000, 2),
            "avg_quality_score": round(avg_quality, 2),
            "connection_failures": self.connection_failures,
            "last_error": self.last_error,
            "last_success": self.last_success.isoformat() if self.last_success else None
        }


class Camera:
    """Enhanced camera class with quality control and buffering"""

    def __init__(self, camera_id: int, url: str, config: CameraConfig):
        self.camera_id = camera_id
        self.url = url
        self.config = config
        self.capture: Optional[cv2.VideoCapture] = None
        self.is_initialized = False
        self.is_active = False
        self.lock = threading.RLock()
        self.frame_buffer = deque(maxlen=config.buffer_size)
        self.metrics = CameraMetrics()
        self.last_frame = None
        self.last_quality = None
        self._stop_event = threading.Event()
        self._capture_thread = None

    def initialize(self) -> bool:
        """Initialize camera with retry logic"""
        for attempt in range(self.config.retry_attempts):
            try:
                logger.info(f"Initializing camera {self.camera_id} (attempt {attempt + 1}/{self.config.retry_attempts})")

                if self.url.isdigit():
                    self.capture = cv2.VideoCapture(int(self.url))
                else:
                    self.capture = cv2.VideoCapture(self.url)

                if not self.capture.isOpened():
                    raise Exception("Failed to open camera")

                # Set camera properties
                self._configure_camera()

                # Warm up camera
                self._warmup()

                self.is_initialized = True
                self.is_active = True
                logger.info(f"Camera {self.camera_id} initialized successfully")
                return True

            except Exception as e:
                logger.error(f"Camera {self.camera_id} initialization failed: {e}")
                self.metrics.connection_failures += 1
                self.metrics.last_error = str(e)

                if self.capture:
                    self.capture.release()
                    self.capture = None

                if attempt < self.config.retry_attempts - 1:
                    time.sleep(self.config.retry_delay)

        return False

    def _configure_camera(self):
        """Configure camera settings for optimal quality"""
        if not self.capture:
            return

        # Set resolution
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.resolution[0])
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.resolution[1])

        # Set FPS
        self.capture.set(cv2.CAP_PROP_FPS, self.config.fps)

        # Set exposure if specified
        if self.config.exposure is not None:
            self.capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Manual mode
            self.capture.set(cv2.CAP_PROP_EXPOSURE, self.config.exposure)
        else:
            self.capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # Auto mode

        # Set gain if specified
        if self.config.gain is not None:
            self.capture.set(cv2.CAP_PROP_GAIN, self.config.gain)

        # Set white balance if specified
        if self.config.white_balance is not None:
            self.capture.set(cv2.CAP_PROP_AUTO_WB, 0)
            self.capture.set(cv2.CAP_PROP_WB_TEMPERATURE, self.config.white_balance)

        # Set focus if specified
        if self.config.focus is not None:
            self.capture.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            self.capture.set(cv2.CAP_PROP_FOCUS, self.config.focus)

        # Additional quality settings
        if self.config.brightness is not None:
            self.capture.set(cv2.CAP_PROP_BRIGHTNESS, self.config.brightness)
        if self.config.contrast is not None:
            self.capture.set(cv2.CAP_PROP_CONTRAST, self.config.contrast)
        if self.config.saturation is not None:
            self.capture.set(cv2.CAP_PROP_SATURATION, self.config.saturation)

        # Enable buffer for smoother capture
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 3)

        logger.info(f"Camera {self.camera_id} configured: {self.config.resolution[0]}x{self.config.resolution[1]} @ {self.config.fps}fps")

    def _warmup(self):
        """Warm up camera by capturing and discarding initial frames"""
        logger.info(f"Warming up camera {self.camera_id}...")
        for _ in range(self.config.warmup_frames):
            ret, _ = self.capture.read()
            if not ret:
                raise Exception("Failed during warmup")
        logger.info(f"Camera {self.camera_id} warmed up")

    def capture_frame(self, validate_quality: bool = True, min_quality_score: float = 50.0) -> Optional[Tuple[np.ndarray, FrameQuality]]:
        """Capture a single frame with quality validation"""
        with self.lock:
            if not self.is_initialized or not self.capture:
                logger.warning(f"Camera {self.camera_id} not initialized")
                return None

            start_time = time.time()

            try:
                # Capture frame
                ret, frame = self.capture.read()

                if not ret or frame is None:
                    self.metrics.record_capture(False, 0)
                    logger.error(f"Failed to capture frame from camera {self.camera_id}")
                    return None

                # Convert to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Validate quality
                quality = self._assess_frame_quality(frame_rgb)

                capture_time = time.time() - start_time
                self.metrics.record_capture(True, capture_time, quality.quality_score)

                # Check if quality meets threshold
                if validate_quality and quality.quality_score < min_quality_score:
                    logger.warning(f"Camera {self.camera_id}: Frame quality below threshold ({quality.quality_score:.2f} < {min_quality_score})")
                    return None

                self.last_frame = frame_rgb
                self.last_quality = quality

                return frame_rgb, quality

            except Exception as e:
                self.metrics.record_capture(False, 0)
                self.metrics.last_error = str(e)
                logger.error(f"Error capturing frame from camera {self.camera_id}: {e}")
                return None

    def _assess_frame_quality(self, frame: np.ndarray) -> FrameQuality:
        """Assess frame quality using multiple metrics"""

        # Convert to grayscale for analysis
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        # 1. Brightness (0-255)
        brightness = np.mean(gray)

        # 2. Sharpness (Laplacian variance)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = laplacian.var()

        # 3. Contrast (standard deviation)
        contrast = np.std(gray)

        # 4. Noise level (estimated from high-frequency components)
        noise_level = self._estimate_noise(gray)

        # 5. Check for blur (low sharpness)
        is_blurred = sharpness < 100

        # 6. Check for overexposure (too bright)
        is_overexposed = brightness > 200 or np.percentile(gray, 95) > 250

        # 7. Check for underexposure (too dark)
        is_underexposed = brightness < 50 or np.percentile(gray, 5) < 20

        # Calculate overall quality score (0-100)
        quality_score = self._calculate_quality_score(
            brightness, sharpness, contrast, noise_level,
            is_blurred, is_overexposed, is_underexposed
        )

        return FrameQuality(
            brightness=float(brightness),
            sharpness=float(sharpness),
            contrast=float(contrast),
            noise_level=float(noise_level),
            is_blurred=is_blurred,
            is_overexposed=is_overexposed,
            is_underexposed=is_underexposed,
            quality_score=quality_score
        )

    def _estimate_noise(self, gray: np.ndarray) -> float:
        """Estimate noise level in image"""
        h, w = gray.shape
        center_h, center_w = h // 2, w // 2
        roi = gray[center_h - 50:center_h + 50, center_w - 50:center_w + 50]

        if roi.size > 0:
            sigma = np.median(np.abs(roi - np.median(roi))) / 0.6745
            return float(sigma)
        return 0.0

    def _calculate_quality_score(self, brightness: float, sharpness: float, contrast: float,
                                 noise_level: float, is_blurred: bool, is_overexposed: bool,
                                 is_underexposed: bool) -> float:
        """Calculate overall quality score (0-100)"""
        score = 100.0

        # Penalize for blur
        if is_blurred:
            score -= 30
        elif sharpness < 200:
            score -= 15

        # Penalize for poor exposure
        if is_overexposed or is_underexposed:
            score -= 25
        elif brightness < 80 or brightness > 180:
            score -= 10

        # Penalize for low contrast
        if contrast < 30:
            score -= 20
        elif contrast < 50:
            score -= 10

        # Penalize for high noise
        if noise_level > 10:
            score -= 20
        elif noise_level > 5:
            score -= 10

        return max(0.0, min(100.0, score))

    def start_continuous_capture(self):
        """Start continuous frame capture in background thread"""
        if self._capture_thread and self._capture_thread.is_alive():
            logger.warning(f"Continuous capture already running for camera {self.camera_id}")
            return

        self._stop_event.clear()
        self._capture_thread = threading.Thread(target=self._continuous_capture_loop, daemon=True)
        self._capture_thread.start()
        logger.info(f"Started continuous capture for camera {self.camera_id}")

    def _continuous_capture_loop(self):
        """Continuous capture loop for buffering frames"""
        while not self._stop_event.is_set():
            try:
                result = self.capture_frame(validate_quality=False)
                if result:
                    frame, quality = result
                    self.frame_buffer.append((frame, quality, time.time()))
                time.sleep(1.0 / self.config.fps)
            except Exception as e:
                logger.error(f"Error in continuous capture loop: {e}")
                time.sleep(0.1)

    def get_latest_frame(self) -> Optional[Tuple[np.ndarray, FrameQuality]]:
        """Get the latest buffered frame"""
        if self.frame_buffer:
            frame, quality, _ = self.frame_buffer[-1]
            return frame, quality
        return None

    def stop_continuous_capture(self):
        """Stop continuous capture"""
        self._stop_event.set()
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
        logger.info(f"Stopped continuous capture for camera {self.camera_id}")

    def release(self):
        """Release camera resources"""
        self.stop_continuous_capture()
        with self.lock:
            if self.capture:
                self.capture.release()
                self.capture = None
            self.is_initialized = False
            self.is_active = False
        logger.info(f"Camera {self.camera_id} released")


class CameraManager:
    """Enhanced camera manager with industrial-grade features"""

    def __init__(self, thread_pool_size: int = 4):
        self.cameras: Dict[int, Camera] = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=thread_pool_size)
        self._is_cloud_environment = self._detect_cloud_environment()

        if self._is_cloud_environment:
            logger.info("Cloud environment detected - using simulator mode")

    def _detect_cloud_environment(self) -> bool:
        """Detect if running in cloud environment"""
        return bool(os.getenv("RENDER") or os.getenv("K_SERVICE") or os.getenv("SPACE_ID"))

    def add_camera(self, camera_id: int, url: str, config: Optional[CameraConfig] = None) -> bool:
        """Add and initialize a camera"""
        with self.lock:
            if camera_id in self.cameras:
                logger.info(f"Removing existing camera {camera_id}")
                self.remove_camera(camera_id)

            # Cloud environment handling
            if self._is_cloud_environment:
                self.cameras[camera_id] = "SIMULATOR"
                logger.info(f"Cloud environment: Camera {camera_id} initialized as SIMULATOR")
                return True

            # Use default config if not provided
            if config is None:
                config = CameraConfig()

            try:
                camera = Camera(camera_id, url, config)
                if camera.initialize():
                    self.cameras[camera_id] = camera
                    logger.info(f"Camera {camera_id} added successfully: {url}")
                    return True
                else:
                    logger.error(f"Failed to initialize camera {camera_id}")
                    return False
            except Exception as e:
                logger.error(f"Error adding camera {camera_id}: {e}")
                return False

    def remove_camera(self, camera_id: int):
        """Remove and release a camera"""
        with self.lock:
            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                if isinstance(camera, Camera):
                    camera.release()
                del self.cameras[camera_id]
                logger.info(f"Camera {camera_id} removed")

    def release_all(self):
        """Release all cameras"""
        with self.lock:
            for camera_id, camera in list(self.cameras.items()):
                if isinstance(camera, Camera):
                    camera.release()
            self.cameras.clear()
            logger.info("All cameras released")

    def capture_frame(self, camera_id: int, validate_quality: bool = True,
                      min_quality_score: float = 50.0):
        """Capture a frame from specified camera.
        Returns (np.ndarray RGB, FrameQuality) tuple or None.
        """
        with self.lock:
            # Cloud simulator
            if self._is_cloud_environment:
                return self._generate_simulator_frame(camera_id)

            # Real camera
            if camera_id not in self.cameras:
                logger.warning(f"Camera {camera_id} not found, attempting auto-discovery")
                self.add_camera(camera_id, str(camera_id))

            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                if isinstance(camera, Camera):
                    return camera.capture_frame(validate_quality, min_quality_score)

            logger.error(f"Failed to capture from camera {camera_id}")
            return None

    def _generate_simulator_frame(self, camera_id: int) -> Tuple[np.ndarray, FrameQuality]:
        """Generate simulated frame for cloud environments"""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Add gradient background
        for i in range(frame.shape[0]):
            frame[i, :] = [min(255, 30 + i // 5), min(255, 40 + i // 8), min(255, 50 + i // 10)]

        # Add text overlays
        cv2.putText(frame, "SIMULATED CAMERA FEED", (80, 180),
                     cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(frame, f"Camera ID: {camera_id}", (180, 230),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        cv2.putText(frame, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     (150, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 255), 1)
        cv2.putText(frame, "Hardware unavailable in cloud environment",
                     (60, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

        # Add moving scan line
        t = int(time.time() * 50) % frame.shape[0]
        cv2.line(frame, (0, t), (frame.shape[1], t), (0, 255, 255), 1)

        # Create quality metrics for simulator
        quality = FrameQuality(
            brightness=128.0,
            sharpness=150.0,
            contrast=50.0,
            noise_level=2.0,
            is_blurred=False,
            is_overexposed=False,
            is_underexposed=False,
            quality_score=85.0
        )

        return frame, quality

    def get_frame(self, camera_id: int) -> Optional[bytes]:
        """Get a frame encoded as JPEG bytes for streaming"""
        with self.lock:
            # Cloud simulator auto-init
            if self._is_cloud_environment:
                if camera_id not in self.cameras:
                    self.cameras[camera_id] = "SIMULATOR"
                    logger.info(f"Auto-initialized SIMULATOR for camera {camera_id}")
                
                result = self._generate_simulator_frame(camera_id)
                if result:
                    frame, _ = result
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    _, buffer = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    return buffer.tobytes()
                return None

            # Real camera auto-discovery
            if camera_id not in self.cameras:
                if camera_id == 0:
                    self.add_camera(0, "0")
                if camera_id not in self.cameras:
                    return None

            camera = self.cameras[camera_id]
            if isinstance(camera, Camera):
                result = camera.capture_frame(validate_quality=False)
                if result:
                    frame, _ = result
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    _, buffer = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    return buffer.tobytes()

            return None

    def test_camera(self, url: str) -> bool:
        """Test if a camera URL is valid and accessible"""
        if self._is_cloud_environment:
            if url.isdigit() or "localhost" in url or "127.0.0.1" in url:
                logger.info(f"Cloud environment: Allowing local camera URL '{url}' without hardware test")
                return True

        try:
            test_config = CameraConfig(warmup_frames=5, retry_attempts=1)
            test_cam = Camera(-1, url, test_config)
            success = test_cam.initialize()
            test_cam.release()
            return success
        except Exception as e:
            logger.error(f"Camera test failed for {url}: {e}")
            return False

    def get_camera_metrics(self, camera_id: int) -> Optional[dict]:
        """Get performance metrics for a camera"""
        with self.lock:
            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                if isinstance(camera, Camera):
                    return camera.metrics.get_stats()
        return None

    def get_all_metrics(self) -> Dict[int, dict]:
        """Get metrics for all cameras"""
        with self.lock:
            metrics = {}
            for camera_id, camera in self.cameras.items():
                if isinstance(camera, Camera):
                    metrics[camera_id] = camera.metrics.get_stats()
            return metrics

    def start_continuous_capture(self, camera_id: int):
        """Start continuous capture for a camera"""
        with self.lock:
            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                if isinstance(camera, Camera):
                    camera.start_continuous_capture()

    def stop_continuous_capture(self, camera_id: int):
        """Stop continuous capture for a camera"""
        with self.lock:
            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                if isinstance(camera, Camera):
                    camera.stop_continuous_capture()

    def get_latest_buffered_frame(self, camera_id: int) -> Optional[Tuple[np.ndarray, FrameQuality]]:
        """Get latest buffered frame from continuous capture"""
        with self.lock:
            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                if isinstance(camera, Camera):
                    return camera.get_latest_frame()
        return None

    def update_camera_config(self, camera_id: int, config: CameraConfig) -> bool:
        """Update camera configuration (requires reinitialization)"""
        with self.lock:
            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                if isinstance(camera, Camera):
                    url = camera.url
                    self.remove_camera(camera_id)
                    return self.add_camera(camera_id, url, config)
        return False
