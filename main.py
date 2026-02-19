from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from datetime import datetime, timedelta
import io
import time
from PIL import Image, ImageEnhance
import asyncio
import os
import numpy as np
import cv2

from database import engine, get_db, Base
from models import InspectionLog, Template, Camera
from schemas import (
    InspectionCreate, InspectionResponse,
    TemplateCreate, TemplateResponse,
    CameraCreate, CameraResponse, CameraUpdate,
    StatsResponse
)
from hf_client import HuggingFaceClient
from camera import CameraManager
from utils import convert_image_to_bytes, cleanup_old_files

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI
app = FastAPI(
    title="Engine Part Detection API - Industrial Grade",
    description="AI-powered engine part defect detection system with advanced quality control",
    version="2.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize managers
hf_client = HuggingFaceClient()
camera_manager = CameraManager()


# ==================== IMAGE PROCESSOR ====================

class ImageProcessor:
    """Advanced image preprocessing for industrial quality"""

    @staticmethod
    def enhance_image(img: Image.Image, auto_adjust: bool = True) -> Image.Image:
        """Enhance image quality for better detection"""
        img_array = np.array(img)

        # Auto color correction
        if auto_adjust:
            img_array = ImageProcessor._auto_color_correction(img_array)

        # Denoise (Faster alternative to prevent timeouts)
        img_array = cv2.GaussianBlur(img_array, (3, 3), 0)

        # Sharpen
        kernel = np.array([[-1, -1, -1],
                           [-1,  9, -1],
                           [-1, -1, -1]])
        img_array = cv2.filter2D(img_array, -1, kernel)

        # Convert back to PIL
        img_enhanced = Image.fromarray(img_array)

        # Enhance contrast and sharpness
        enhancer = ImageEnhance.Contrast(img_enhanced)
        img_enhanced = enhancer.enhance(1.2)

        enhancer = ImageEnhance.Sharpness(img_enhanced)
        img_enhanced = enhancer.enhance(1.3)

        return img_enhanced

    @staticmethod
    def _auto_color_correction(img: np.ndarray) -> np.ndarray:
        """Automatic color correction using white balance"""
        result = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        avg_a = np.average(result[:, :, 1])
        avg_b = np.average(result[:, :, 2])
        result[:, :, 1] = result[:, :, 1] - ((avg_a - 128) * (result[:, :, 0] / 255.0) * 1.1)
        result[:, :, 2] = result[:, :, 2] - ((avg_b - 128) * (result[:, :, 0] / 255.0) * 1.1)
        result = cv2.cvtColor(result, cv2.COLOR_LAB2RGB)
        return result

    @staticmethod
    def validate_image_quality(img: Image.Image, min_resolution: tuple = (320, 240)) -> tuple:
        """Validate image meets quality standards - Relaxed constraints"""
        width, height = img.size

        if width < min_resolution[0] or height < min_resolution[1]:
            return False, f"Image resolution too low: {width}x{height} (minimum: {min_resolution[0]}x{min_resolution[1]})"

        aspect_ratio = width / height
        if aspect_ratio < 0.2 or aspect_ratio > 5.0:  # Relaxed aspect ratio
            return False, f"Unusual aspect ratio: {aspect_ratio:.2f}"

        img_array = np.array(img)
        brightness = np.mean(img_array)
        if brightness < 15:  # Relaxed: was 30
            return False, "Image too dark"
        if brightness > 245:  # Relaxed: was 225
            return False, "Image too bright"

        contrast = np.std(img_array)
        if contrast < 5:  # Relaxed: was 20
            return False, "Image has insufficient contrast"

        return True, "OK"

    @staticmethod
    def prepare_for_detection(img: Image.Image, target_size: tuple = (1024, 1024)) -> Image.Image:
        """Prepare image for AI detection - higher resolution for localization"""
        img_enhanced = ImageProcessor.enhance_image(img)
        img_enhanced.thumbnail(target_size, Image.Resampling.LANCZOS)
        return img_enhanced


image_processor = ImageProcessor()


# ==================== STARTUP / SHUTDOWN ====================

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("=" * 60)
    logger.info("Starting Engine Detection API - Industrial Grade")
    logger.info("=" * 60)

    # Database schema migration
    try:
        from sqlalchemy import text, inspect as sa_inspect

        with engine.connect() as conn:
            inspector = sa_inspect(engine)

            # --- templates table ---
            if 'templates' in inspector.get_table_names():
                template_cols = [col['name'] for col in inspector.get_columns('templates')]
                if 'name' not in template_cols:
                    conn.execute(text("ALTER TABLE templates ADD COLUMN name VARCHAR(100)"))
                    conn.commit()
                if 'image_count' not in template_cols:
                    conn.execute(text("ALTER TABLE templates ADD COLUMN image_count INTEGER DEFAULT 0"))
                    conn.commit()
                try:
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_templates_name ON templates (name)"))
                    conn.commit()
                except:
                    pass

            # --- cameras table ---
            if 'cameras' in inspector.get_table_names():
                camera_cols = [col['name'] for col in inspector.get_columns('cameras')]
                for col_name, col_def in [
                    ('camera_type', "VARCHAR(20) DEFAULT 'ip'"),
                    ('url', "VARCHAR(500)"),
                    ('is_active', "BOOLEAN DEFAULT TRUE"),
                    ('last_used', "TIMESTAMP"),
                ]:
                    if col_name not in camera_cols:
                        conn.execute(text(f"ALTER TABLE cameras ADD COLUMN {col_name} {col_def}"))
                        conn.commit()

            # --- inspection_logs schema migration ---
            if 'inspection_logs' in inspector.get_table_names():
                log_cols = [col['name'] for col in inspector.get_columns('inspection_logs')]
                for col_name in ['quality_score', 'image_brightness', 'image_sharpness']:
                    if col_name not in log_cols:
                        conn.execute(text(f"ALTER TABLE inspection_logs ADD COLUMN {col_name} FLOAT"))
                        conn.commit()
                # Persistence column
                if 'processed_image' not in log_cols:
                    conn.execute(text("ALTER TABLE inspection_logs ADD COLUMN processed_image TEXT"))
                    conn.commit()

            logger.info("Database schema migration completed")

    except Exception as e:
        logger.error(f"Schema migration error: {e}")

    # Initialize cameras from auto-detection
    available_cams = camera_manager.get_available_cameras()
    logger.info(f"Startup: Auto-detected cameras at indices {available_cams}")

    # Proactive HuggingFace Warm-up
    def warmup_hf():
        try:
            logger.info("Startup: Prompting HuggingFace client warm-up...")
            _ = hf_client.client
        except Exception as e:
            logger.warning(f"HF Warm-up failed: {e}")

    # Run warm-up in a separate thread to not block main startup
    import threading
    threading.Thread(target=warmup_hf, daemon=True).start()

    # Start background tasks
    asyncio.create_task(periodic_cleanup())
    
    logger.info("System initialization complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down...")
    camera_manager.release_all()
    logger.info("Shutdown complete")


async def periodic_cleanup():
    """Periodic cleanup of old temp files"""
    while True:
        try:
            cleanup_old_files()
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(3600)


async def periodic_camera_health_check():
    """Periodic health check for all cameras"""
    # Simplified for auto-detection: just log active camera status
    while True:
        try:
            await asyncio.sleep(300)
            if camera_manager.active_camera_id is not None:
                logger.info(f"Health check: Camera {camera_manager.active_camera_id} is active")
        except Exception as e:
            logger.error(f"Health check error: {e}")


# ==================== ROUTES ====================

@app.get("/")
async def read_root():
    """Serve main dashboard HTML"""
    return FileResponse("static/index.html")


# ==================== DASHBOARD & STATS ====================

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics"""
    try:
        total_scans = db.query(InspectionLog).count()
        pass_count = db.query(InspectionLog).filter(InspectionLog.status == "PASS").count()
        fail_count = db.query(InspectionLog).filter(InspectionLog.status == "FAIL").count()

        return StatsResponse(
            total_scans=total_scans,
            pass_count=pass_count,
            fail_count=fail_count
        )
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history", response_model=List[InspectionResponse])
async def get_history(limit: int = 100, skip: int = 0, db: Session = Depends(get_db)):
    """Get inspection history"""
    try:
        inspections = db.query(InspectionLog)\
            .order_by(InspectionLog.timestamp.desc())\
            .offset(skip).limit(limit).all()
        return inspections
    except Exception as e:
        logger.error(f"History fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history/recent")
async def get_recent_history(hours: int = 24, db: Session = Depends(get_db)):
    """Get recent inspection history"""
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        inspections = db.query(InspectionLog)\
            .filter(InspectionLog.timestamp >= cutoff_time)\
            .order_by(InspectionLog.timestamp.desc()).all()

        return [
            {
                "id": insp.id,
                "timestamp": insp.timestamp.isoformat(),
                "status": insp.status,
                "confidence": insp.confidence,
                "matched_part": insp.matched_part,
                "quality_score": insp.quality_score
            }
            for insp in inspections
        ]
    except Exception as e:
        logger.error(f"Recent history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== TEMPLATE MANAGEMENT ====================

@app.post("/api/templates", response_model=TemplateResponse)
async def create_template(
    name: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """Upload samples to a Class Cluster with quality validation"""
    try:
        if len(files) < 1 or len(files) > 10:
            raise HTTPException(status_code=400, detail="Please upload between 1 and 10 samples")

        template_images = []
        quality_issues = []

        for idx, file in enumerate(files):
            contents = await file.read()
            img = Image.open(io.BytesIO(contents))

            is_valid, message = image_processor.validate_image_quality(img)
            if not is_valid:
                quality_issues.append(f"Sample {idx + 1}: {message}")
                continue

            img_processed = image_processor.prepare_for_detection(img)
            template_images.append(img_processed)

        if not template_images:
            raise HTTPException(
                status_code=400,
                detail=f"No valid images. Issues: {'; '.join(quality_issues)}"
            )

        # Call HF Cloud to add samples to the class cluster
        result = await hf_client.save_template(name, template_images)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to register class samples"))

        # Check if class already exists
        db_template = db.query(Template).filter(Template.name == name).first()
        
        if db_template:
            # Update existing class cluster
            db_template.image_count += len(template_images)
            logger.info(f"Class Cluster '{name}' updated. Total samples: {db_template.image_count}")
        else:
            # Create new class cluster
            db_template = Template(
                name=name,
                image_count=len(template_images),
                created_at=datetime.utcnow()
            )
            db.add(db_template)
            logger.info(f"New Class Cluster '{name}' created with {len(template_images)} samples")
            
        db.commit()
        db.refresh(db_template)

        if quality_issues:
            logger.warning(f"Class Cluster '{name}' updates had quality issues: {quality_issues}")

        return db_template

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Template creation error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/templates", response_model=List[TemplateResponse])
async def list_templates(db: Session = Depends(get_db)):
    """List all templates"""
    try:
        templates = db.query(Template).all()
        return [
            {"id": t.id, "name": t.name, "image_count": t.image_count, "created_at": t.created_at}
            for t in templates
        ]
    except Exception as e:
        logger.error(f"Template list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    """Delete a template"""
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        await hf_client.delete_template(template.name)
        db.delete(template)
        db.commit()

        logger.info(f"Template '{template.name}' deleted")
        return {"message": "Template deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Template deletion error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== INSPECTION / DETECTION ====================

@app.post("/api/scan")
async def scan_image(
    file: UploadFile = File(...),
    threshold: float = 0.92,
    enhance: bool = True,
    db: Session = Depends(get_db)
):
    """Scan uploaded image with advanced preprocessing"""
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))

        # Validate quality
        is_valid, message = image_processor.validate_image_quality(img)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Image quality insufficient: {message}")

        # Enhance or resize
        if enhance:
            img_processed = image_processor.prepare_for_detection(img)
        else:
            img_processed = img.resize((224, 224))

        # Assess quality metrics
        img_array = np.array(img_processed)
        brightness = float(np.mean(img_array))
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = float(laplacian.var())

        # Call HuggingFace detection
        result = await hf_client.detect_part(img_processed, threshold)

        if not result.get("success"):
            raise HTTPException(status_code=502, detail=f"AI Engine Error: {result.get('error')}")

        status = "PASS" if result.get("matched") else "FAIL"
        
        # Convert visualization image to base64 if it exists
        vis_base64 = None
        vis_path = result.get("visualization")
        if vis_path and os.path.exists(vis_path):
            with open(vis_path, "rb") as image_file:
                import base64
                vis_base64 = base64.b64encode(image_file.read()).decode('utf-8')

        # Log to database
        log_entry = InspectionLog(
            timestamp=datetime.utcnow(),
            status=status,
            confidence=result.get("confidence", 0.0),
            matched_part=result.get("best_match"),
            source="upload",
            quality_score=min(100.0, sharpness / 2),
            image_brightness=brightness,
            image_sharpness=sharpness,
            processed_image=vis_base64
        )
        db.add(log_entry)
        db.commit()

        logger.info(f"Scan completed: {status} (confidence: {result.get('confidence', 0):.3f})")

        return {
            "success": True,
            "status": status,
            "confidence": result.get("confidence"),
            "matched_part": result.get("best_match"),
            "all_results": result.get("all_results", []),
            "log_id": log_entry.id,
            "visualization": vis_base64,
            "quality_metrics": {
                "brightness": round(brightness, 2),
                "sharpness": round(sharpness, 2)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/capture_and_scan")
async def capture_and_scan(
    camera_id: Optional[int] = 0,
    threshold: float = 0.92,
    db: Session = Depends(get_db)
):
    """Capture from camera and scan - optimized for speed"""
    try:
        start_time = time.time()

        # Capture frame
        img = camera_manager.capture_frame(camera_id)

        if img is None:
            if os.getenv("RENDER") or os.getenv("K_SERVICE"):
                return {
                    "success": False,
                    "error": "Hardware camera not available in cloud environment. Please use 'Upload Scan' instead.",
                    "status": "N/A"
                }
            raise HTTPException(
                status_code=500,
                detail="Failed to capture frame. Check camera connection."
            )

        capture_time = time.time() - start_time

        # Resize for stability but keep enough resolution for localization (circles)
        img = img.resize((1024, 1024), Image.Resampling.LANCZOS) if img.width > 1024 else img

        # Calculate basic quality metrics
        img_array = np.array(img)
        brightness = float(np.mean(img_array))
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = float(laplacian.var())

        # Detect via HF Space
        detection_result = await hf_client.detect_part(img, threshold)
        
        if not detection_result.get("success"):
            return {
                "success": False,
                "error": f"AI Engine Connection Failed: {detection_result.get('error')}",
                "status": "ERROR"
            }

        total_time = time.time() - start_time

        status = "PASS" if detection_result.get("matched") else "FAIL"
        
        # Convert visualization image to base64 if it exists
        vis_base64 = None
        vis_path = detection_result.get("visualization")
        if vis_path and os.path.exists(vis_path):
            with open(vis_path, "rb") as image_file:
                import base64
                vis_base64 = base64.b64encode(image_file.read()).decode('utf-8')

        # Log to database
        log_entry = InspectionLog(
            timestamp=datetime.utcnow(),
            status=status,
            confidence=detection_result.get("confidence", 0.0),
            matched_part=detection_result.get("best_match"),
            source=f"camera_{camera_id}",
            quality_score=min(100.0, sharpness / 2),
            image_brightness=brightness,
            image_sharpness=sharpness,
            processed_image=vis_base64
        )
        db.add(log_entry)
        db.commit()

        logger.info(f"Camera scan: {status} | confidence={detection_result.get('confidence', 0):.3f} | total={total_time:.2f}s")

        return {
            "success": True,
            "status": status,
            "confidence": detection_result.get("confidence"),
            "matched_part": detection_result.get("best_match"),
            "log_id": log_entry.id,
            "visualization": vis_base64,
            "quality_metrics": {
                "quality_score": round(min(100.0, sharpness / 2), 2),
                "brightness": round(brightness, 2),
                "sharpness": round(sharpness, 2),
                "contrast": 0.0, # Not calculated for speed
                "is_blurred": sharpness < 100.0 # Simple threshold
            },
            "timing": {
                "capture_ms": round(capture_time * 1000),
                "total_ms": round(total_time * 1000)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Capture and scan error: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CAMERA MANAGEMENT ====================


# ==================== CAMERA MANAGEMENT ====================

@app.get("/api/video_feed")
async def video_feed(camera_id: int = 0):
    """Stream video feed from camera"""
    def generate():
        while True:
            frame_bytes = camera_manager.get_frame(camera_id)
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                time.sleep(0.1)  # Wait a bit if frame is not available
            time.sleep(0.03)  # Approx 30 FPS

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/cameras")
async def list_cameras():
    """List all available cameras (auto-detected)"""
    try:
        # Re-scan for cameras on request to handle plug/unplug
        cameras = camera_manager.get_available_cameras()
        return [
            {"id": i, "name": f"Camera {i}", "is_active": True, "camera_type": "usb", "url": str(i)}
            for i in cameras
        ]
    except Exception as e:
        logger.error(f"Camera list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

#         while True:
#             try:
#                 frame = camera_manager.get_frame(camera_id)
#                 if frame is not None:
#                     yield (b'--frame\r\n'
#                            b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
#                 else:
#                     time.sleep(0.033)  # ~30 FPS
#             except Exception as e:
#                 logger.error(f"Video feed error: {e}")
#                 break
# 
#     return StreamingResponse(
#         generate(),
#         media_type="multipart/x-mixed-replace; boundary=frame",
#         headers={
#             "Cache-Control": "no-cache, no-store, must-revalidate",
#             "Pragma": "no-cache",
#             "Expires": "0",
#             "X-Accel-Buffering": "no"
#         }
#     )


# Camera management endpoints disabled


# ==================== EXPORT ====================

@app.get("/api/export/history")
async def export_history(db: Session = Depends(get_db)):
    """Export history to CSV with quality metrics"""
    try:
        import csv
        from io import StringIO

        inspections = db.query(InspectionLog).order_by(InspectionLog.timestamp.desc()).all()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Timestamp", "Status", "Confidence", "Matched Part",
            "Source", "Quality Score", "Brightness", "Sharpness"
        ])

        for insp in inspections:
            writer.writerow([
                insp.id,
                insp.timestamp.isoformat(),
                insp.status,
                insp.confidence,
                insp.matched_part or "N/A",
                insp.source,
                insp.quality_score or "N/A",
                insp.image_brightness or "N/A",
                insp.image_sharpness or "N/A"
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=inspection_history.csv"}
        )

    except Exception as e:
        logger.error(f"Export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== HEALTH & MONITORING ====================

# @app.get("/health")
# async def health_check():
#     """Comprehensive health check"""
#     try:
#         # camera_metrics = camera_manager.get_all_metrics()
#         return {
#             "status": "healthy",
#             "timestamp": datetime.utcnow().isoformat(),
#             "cameras": {
#                 "total": 0,
#                 "metrics": {}
#             }
#         }
#     except Exception as e:
#         logger.error(f"Health check error: {e}")
#         return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


@app.get("/api/system/status")
async def system_status(db: Session = Depends(get_db)):
    """Get detailed system status"""
    try:
        total_inspections = db.query(InspectionLog).count()
        total_templates = db.query(Template).count()
        total_cameras = db.query(Camera).count()
        active_cameras = db.query(Camera).filter(Camera.is_active == True).count()

        recent = db.query(InspectionLog).order_by(InspectionLog.timestamp.desc()).limit(100).all()
        recent_pass_rate = 0
        if recent:
            passes = sum(1 for log in recent if log.status == "PASS")
            recent_pass_rate = (passes / len(recent)) * 100

        return {
            "database": {
                "total_inspections": total_inspections,
                "total_templates": total_templates,
                "total_cameras": total_cameras,
                "active_cameras": active_cameras
            },
            "performance": {
                "recent_pass_rate": round(recent_pass_rate, 2),
                "recent_sample_size": len(recent)
            },
            # "cameras": camera_manager.get_all_metrics(),
            "cameras": {},
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"System status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
