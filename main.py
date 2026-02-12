# from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks
# from fastapi.staticfiles import StaticFiles
# from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
# from fastapi.middleware.cors import CORSMiddleware
# from sqlalchemy.orm import Session
# from typing import List, Optional
# import logging
# from datetime import datetime, timedelta
# import io
# from PIL import Image
# import asyncio

# from database import engine, get_db, Base
# from models import InspectionLog, Template, Camera
# from schemas import (
#     InspectionCreate, InspectionResponse, 
#     TemplateCreate, TemplateResponse,
#     CameraCreate, CameraResponse, CameraUpdate,
#     StatsResponse
# )
# from hf_client import HuggingFaceClient
# from camera_manager import CameraManager
# from utils import convert_image_to_bytes, cleanup_old_files

# # Configure logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# # Create tables
# Base.metadata.create_all(bind=engine)

# # Initialize FastAPI
# app = FastAPI(
#     title="Engine Part Detection API",
#     description="AI-powered engine part defect detection system",
#     version="1.0.0"
# )

# # CORS Configuration
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # Mount static files
# app.mount("/static", StaticFiles(directory="static"), name="static")

# # Initialize managers
# hf_client = HuggingFaceClient()
# camera_manager = CameraManager()

# # Cleanup task
# # @app.on_event("startup")
# # async def startup_event():
# #     """Initialize services on startup"""
# #     logger.info("Starting Engine Detection API...")
    
# #     # Simple schema synchronization for missing columns
# #     try:
# #         from sqlalchemy import text
# #         with engine.connect() as conn:
# #             # Table: templates
# #             cols_templates = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='templates'")).fetchall()
# #             cols_templates = [c[0] for c in cols_templates]
            
# #             if 'name' not in cols_templates:
# #                 logger.info("Adding 'name' column to 'templates'")
# #                 conn.execute(text("ALTER TABLE templates ADD COLUMN name VARCHAR(100)"))
# #                 conn.execute(text("CREATE UNIQUE INDEX ix_templates_name ON templates (name)"))
            
# #             if 'image_count' not in cols_templates:
# #                 logger.info("Adding 'image_count' column to 'templates'")
# #                 conn.execute(text("ALTER TABLE templates ADD COLUMN image_count INTEGER"))

# #             # Table: cameras
# #             cols_cameras = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='cameras'")).fetchall()
# #             cols_cameras = [c[0] for c in cols_cameras]
            
# #             if 'camera_type' not in cols_cameras:
# #                 logger.info("Adding 'camera_type' column to 'cameras'")
# #                 conn.execute(text("ALTER TABLE cameras ADD COLUMN camera_type VARCHAR(20)"))
            
# #             conn.commit()
# #             logger.info("Database schema sync completed.")
# #     except Exception as e:
# #         logger.warning(f"Schema sync warning: {e}")

# #     asyncio.create_task(periodic_cleanup())

# @app.on_event("startup")
# async def startup_event():
#     """Initialize services on startup"""
#     logger.info("Starting Engine Detection API...")
    
#     # Database schema migration
#     try:
#         from sqlalchemy import text, inspect
        
#         with engine.connect() as conn:
#             inspector = inspect(engine)
            
#             # Check templates table
#             if 'templates' in inspector.get_table_names():
#                 template_cols = [col['name'] for col in inspector.get_columns('templates')]
                
#                 if 'name' not in template_cols:
#                     logger.info("Adding 'name' column to 'templates'")
#                     conn.execute(text("ALTER TABLE templates ADD COLUMN name VARCHAR(100)"))
#                     conn.commit()
                
#                 if 'image_count' not in template_cols:
#                     logger.info("Adding 'image_count' column to 'templates'")
#                     conn.execute(text("ALTER TABLE templates ADD COLUMN image_count INTEGER DEFAULT 0"))
#                     conn.commit()
                
#                 # Add unique index on name if not exists
#                 try:
#                     conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_templates_name ON templates (name)"))
#                     conn.commit()
#                 except:
#                     pass
            
#             # Check cameras table
#             if 'cameras' in inspector.get_table_names():
#                 camera_cols = [col['name'] for col in inspector.get_columns('cameras')]
                
#                 if 'camera_type' not in camera_cols:
#                     logger.info("Adding 'camera_type' column to 'cameras'")
#                     conn.execute(text("ALTER TABLE cameras ADD COLUMN camera_type VARCHAR(20) DEFAULT 'ip'"))
#                     conn.commit()
                
#                 if 'url' not in camera_cols:
#                     logger.info("Adding 'url' column to 'cameras'")
#                     conn.execute(text("ALTER TABLE cameras ADD COLUMN url VARCHAR(500)"))
#                     conn.commit()
                
#                 if 'is_active' not in camera_cols:
#                     logger.info("Adding 'is_active' column to 'cameras'")
#                     conn.execute(text("ALTER TABLE cameras ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
#                     conn.commit()
            
#             logger.info("✅ Database schema migration completed")
            
#     except Exception as e:
#         logger.error(f"⚠️ Schema migration error: {e}")
    
#     # Start periodic cleanup
#     asyncio.create_task(periodic_cleanup())

# @app.on_event("shutdown")
# async def shutdown_event():
#     """Cleanup on shutdown"""
#     logger.info("Shutting down...")
#     camera_manager.release_all()

# async def periodic_cleanup():
#     """Periodic cleanup of old files and resources"""
#     while True:
#         try:
#             cleanup_old_files()
#             await asyncio.sleep(3600)  # Every hour
#         except Exception as e:
#             logger.error(f"Cleanup error: {e}")

# # ==================== ROUTES ====================

# @app.get("/")
# async def read_root():
#     """Serve main dashboard HTML"""
#     return FileResponse("static/index.html")

# # ==================== DASHBOARD & STATS ====================

# @app.get("/api/stats", response_model=StatsResponse)
# async def get_stats(db: Session = Depends(get_db)):
#     """Get dashboard statistics"""
#     try:
#         total_scans = db.query(InspectionLog).count()
#         perfect_count = db.query(InspectionLog).filter(
#             InspectionLog.status == "PERFECT"
#         ).count()
#         defected_count = db.query(InspectionLog).filter(
#             InspectionLog.status == "DEFECTIVE"
#         ).count()
        
#         return StatsResponse(
#             total_scans=total_scans,
#             perfect_count=perfect_count,
#             defected_count=defected_count
#         )
#     except Exception as e:
#         logger.error(f"Stats error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/history", response_model=List[InspectionResponse])
# async def get_history(
#     limit: int = 100,
#     skip: int = 0,
#     db: Session = Depends(get_db)
# ):
#     """Get inspection history"""
#     try:
#         inspections = db.query(InspectionLog)\
#             .order_by(InspectionLog.timestamp.desc())\
#             .offset(skip)\
#             .limit(limit)\
#             .all()
#         return inspections
#     except Exception as e:
#         logger.error(f"History fetch error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/history/recent")
# async def get_recent_history(hours: int = 24, db: Session = Depends(get_db)):
#     """Get recent inspection history"""
#     try:
#         cutoff_time = datetime.utcnow() - timedelta(hours=hours)
#         inspections = db.query(InspectionLog)\
#             .filter(InspectionLog.timestamp >= cutoff_time)\
#             .order_by(InspectionLog.timestamp.desc())\
#             .all()
        
#         return [
#             {
#                 "id": insp.id,
#                 "timestamp": insp.timestamp.isoformat(),
#                 "status": insp.status,
#                 "confidence": insp.confidence,
#                 "matched_part": insp.matched_part
#             }
#             for insp in inspections
#         ]
#     except Exception as e:
#         logger.error(f"Recent history error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# # ==================== TEMPLATE MANAGEMENT ====================

# @app.post("/api/templates", response_model=TemplateResponse)
# async def create_template(
#     name: str,
#     files: List[UploadFile] = File(...),
#     db: Session = Depends(get_db)
# ):
#     """Upload template images to HuggingFace Space"""
#     try:
#         if len(files) < 3 or len(files) > 10:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Please upload between 3 and 10 template images"
#             )
        
#         # Process images
#         template_images = []
#         for file in files:
#             contents = await file.read()
#             img = Image.open(io.BytesIO(contents))
            
#             # Resize for consistency
#             img = img.resize((224, 224))
#             template_images.append(img)
        
#         # Send to HuggingFace Space
#         result = await hf_client.save_template(name, template_images)
        
#         if not result.get("success"):
#             raise HTTPException(
#                 status_code=500,
#                 detail=result.get("error", "Failed to save template")
#             )
        
#         # Save to database
#         db_template = Template(
#             name=name,
#             image_count=len(files),
#             created_at=datetime.utcnow()
#         )
#         db.add(db_template)
#         db.commit()
#         db.refresh(db_template)
        
#         logger.info(f"Template '{name}' created with {len(files)} images")
#         return db_template
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Template creation error: {e}")
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/templates", response_model=List[TemplateResponse])
# async def list_templates(db: Session = Depends(get_db)):
#     """List all templates"""
#     try:
#         # Get from HuggingFace
#         hf_templates = await hf_client.list_templates()
        
#         # Sync with database
#         templates = db.query(Template).all()
        
#         return [
#             {
#                 "id": t.id,
#                 "name": t.name,
#                 "image_count": t.image_count,
#                 "created_at": t.created_at
#             }
#             for t in templates
#         ]
#     except Exception as e:
#         logger.error(f"Template list error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @app.delete("/api/templates/{template_id}")
# async def delete_template(template_id: int, db: Session = Depends(get_db)):
#     """Delete a template"""
#     try:
#         template = db.query(Template).filter(Template.id == template_id).first()
#         if not template:
#             raise HTTPException(status_code=404, detail="Template not found")
        
#         # Delete from HuggingFace
#         await hf_client.delete_template(template.name)
        
#         # Delete from database
#         db.delete(template)
#         db.commit()
        
#         return {"message": "Template deleted successfully"}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Template deletion error: {e}")
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# # ==================== INSPECTION / DETECTION ====================

# @app.post("/api/scan")
# async def scan_image(
#     file: UploadFile = File(...),
#     threshold: float = 0.7,
#     background_tasks: BackgroundTasks = BackgroundTasks(),
#     db: Session = Depends(get_db)
# ):
#     """Scan uploaded image for defects"""
#     try:
#         # Read and validate image
#         contents = await file.read()
#         img = Image.open(io.BytesIO(contents))
        
#         # Call HuggingFace detection
#         result = await hf_client.detect_part(img, threshold)
        
#         # Determine status
#         status = "PERFECT" if result.get("matched") else "DEFECTIVE"
        
#         # Log to database
#         log_entry = InspectionLog(
#             timestamp=datetime.utcnow(),
#             status=status,
#             confidence=result.get("confidence", 0.0),
#             matched_part=result.get("best_match"),
#             source="upload"
#         )
#         db.add(log_entry)
#         db.commit()
        
#         logger.info(f"Scan completed: {status} (confidence: {result.get('confidence')})")
        
#         return {
#             "success": True,
#             "status": status,
#             "confidence": result.get("confidence"),
#             "matched_part": result.get("best_match"),
#             "all_results": result.get("all_results", []),
#             "log_id": log_entry.id
#         }
        
#     except Exception as e:
#         logger.error(f"Scan error: {e}")
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/capture_and_scan")
# async def capture_and_scan(
#     camera_id: Optional[int] = 0,
#     threshold: float = 0.7,
#     db: Session = Depends(get_db)
# ):
#     """Capture from camera and scan"""
#     try:
#         # Capture frame
#         frame = camera_manager.capture_frame(camera_id)
#         if frame is None:
#             raise HTTPException(status_code=500, detail="Failed to capture frame")
        
#         # Convert to PIL Image
#         img = Image.fromarray(frame)
        
#         # Detect
#         result = await hf_client.detect_part(img, threshold)
        
#         status = "PERFECT" if result.get("matched") else "DEFECTIVE"
        
#         # Log to database
#         log_entry = InspectionLog(
#             timestamp=datetime.utcnow(),
#             status=status,
#             confidence=result.get("confidence", 0.0),
#             matched_part=result.get("best_match"),
#             source=f"camera_{camera_id}"
#         )
#         db.add(log_entry)
#         db.commit()
        
#         return {
#             "success": True,
#             "status": status,
#             "confidence": result.get("confidence"),
#             "matched_part": result.get("best_match"),
#             "log_id": log_entry.id
#         }
        
#     except Exception as e:
#         logger.error(f"Capture and scan error: {e}")
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# # ==================== CAMERA MANAGEMENT ====================

# @app.get("/api/video_feed")
# async def video_feed(camera_id: int = 0):
#     """Stream video feed from camera"""
#     def generate():
#         while True:
#             try:
#                 frame = camera_manager.get_frame(camera_id)
#                 if frame is not None:
#                     yield (b'--frame\r\n'
#                            b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
#                 else:
#                     break
#             except Exception as e:
#                 logger.error(f"Video feed error: {e}")
#                 break
    
#     return StreamingResponse(
#         generate(),
#         media_type="multipart/x-mixed-replace; boundary=frame"
#     )

# @app.post("/api/cameras", response_model=CameraResponse)
# async def create_camera(camera: CameraCreate, db: Session = Depends(get_db)):
#     """Add new camera"""
#     try:
#         # Test connection
#         success = camera_manager.test_camera(camera.url)
#         if not success:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Cannot connect to camera"
#             )
        
#         db_camera = Camera(
#             name=camera.name,
#             camera_type=camera.camera_type,
#             url=camera.url,
#             is_active=True,
#             created_at=datetime.utcnow()
#         )
#         db.add(db_camera)
#         db.commit()
#         db.refresh(db_camera)
        
#         # Add to camera manager
#         camera_manager.add_camera(db_camera.id, camera.url)
        
#         logger.info(f"Camera '{camera.name}' added successfully")
#         return db_camera
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Camera creation error: {e}")
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/cameras", response_model=List[CameraResponse])
# async def list_cameras(db: Session = Depends(get_db)):
#     """List all cameras"""
#     try:
#         cameras = db.query(Camera).all()
#         return cameras
#     except Exception as e:
#         logger.error(f"Camera list error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @app.put("/api/cameras/{camera_id}", response_model=CameraResponse)
# async def update_camera(
#     camera_id: int,
#     camera_update: CameraUpdate,
#     db: Session = Depends(get_db)
# ):
#     """Update camera settings"""
#     try:
#         camera = db.query(Camera).filter(Camera.id == camera_id).first()
#         if not camera:
#             raise HTTPException(status_code=404, detail="Camera not found")
        
#         if camera_update.name:
#             camera.name = camera_update.name
#         if camera_update.url:
#             camera.url = camera_update.url
#         if camera_update.is_active is not None:
#             camera.is_active = camera_update.is_active
        
#         db.commit()
#         db.refresh(camera)
#         return camera
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Camera update error: {e}")
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# @app.delete("/api/cameras/{camera_id}")
# async def delete_camera(camera_id: int, db: Session = Depends(get_db)):
#     """Delete camera"""
#     try:
#         camera = db.query(Camera).filter(Camera.id == camera_id).first()
#         if not camera:
#             raise HTTPException(status_code=404, detail="Camera not found")
        
#         camera_manager.remove_camera(camera_id)
#         db.delete(camera)
#         db.commit()
        
#         return {"message": "Camera deleted successfully"}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Camera deletion error: {e}")
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/cameras/test")
# async def test_camera_connection(url: str):
#     """Test camera connection"""
#     try:
#         success = camera_manager.test_camera(url)
#         return {"success": success}
#     except Exception as e:
#         logger.error(f"Camera test error: {e}")
#         return {"success": False, "error": str(e)}

# # ==================== EXPORT ====================

# @app.get("/api/export/history")
# async def export_history(db: Session = Depends(get_db)):
#     """Export history to CSV"""
#     try:
#         import csv
#         from io import StringIO
        
#         inspections = db.query(InspectionLog).order_by(
#             InspectionLog.timestamp.desc()
#         ).all()
        
#         output = StringIO()
#         writer = csv.writer(output)
#         writer.writerow(["ID", "Timestamp", "Status", "Confidence", "Matched Part", "Source"])
        
#         for insp in inspections:
#             writer.writerow([
#                 insp.id,
#                 insp.timestamp.isoformat(),
#                 insp.status,
#                 insp.confidence,
#                 insp.matched_part or "N/A",
#                 insp.source
#             ])
        
#         output.seek(0)
#         return StreamingResponse(
#             iter([output.getvalue()]),
#             media_type="text/csv",
#             headers={"Content-Disposition": "attachment; filename=inspection_history.csv"}
#         )
        
#     except Exception as e:
#         logger.error(f"Export error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# # Health check
# @app.get("/health")
# async def health_check():
#     """Health check endpoint"""
#     return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}




from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from datetime import datetime, timedelta
import io
from PIL import Image
import asyncio
import os

from database import engine, get_db, Base
from models import InspectionLog, Template, Camera
from schemas import (
    InspectionCreate, InspectionResponse, 
    TemplateCreate, TemplateResponse,
    CameraCreate, CameraResponse, CameraUpdate,
    StatsResponse
)
from hf_client import HuggingFaceClient
from camera_manager import CameraManager
from utils import convert_image_to_bytes, cleanup_old_files

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI
app = FastAPI(
    title="Engine Part Detection API",
    description="AI-powered engine part defect detection system",
    version="1.0.0"
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

# Cleanup task
# @app.on_event("startup")
# async def startup_event():
#     """Initialize services on startup"""
#     logger.info("Starting Engine Detection API...")
    
#     # Simple schema synchronization for missing columns
#     try:
#         from sqlalchemy import text
#         with engine.connect() as conn:
#             # Table: templates
#             cols_templates = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='templates'")).fetchall()
#             cols_templates = [c[0] for c in cols_templates]
            
#             if 'name' not in cols_templates:
#                 logger.info("Adding 'name' column to 'templates'")
#                 conn.execute(text("ALTER TABLE templates ADD COLUMN name VARCHAR(100)"))
#                 conn.execute(text("CREATE UNIQUE INDEX ix_templates_name ON templates (name)"))
            
#             if 'image_count' not in cols_templates:
#                 logger.info("Adding 'image_count' column to 'templates'")
#                 conn.execute(text("ALTER TABLE templates ADD COLUMN image_count INTEGER"))

#             # Table: cameras
#             cols_cameras = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='cameras'")).fetchall()
#             cols_cameras = [c[0] for c in cols_cameras]
            
#             if 'camera_type' not in cols_cameras:
#                 logger.info("Adding 'camera_type' column to 'cameras'")
#                 conn.execute(text("ALTER TABLE cameras ADD COLUMN camera_type VARCHAR(20)"))
            
#             conn.commit()
#             logger.info("Database schema sync completed.")
#     except Exception as e:
#         logger.warning(f"Schema sync warning: {e}")

#     asyncio.create_task(periodic_cleanup())

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting Engine Detection API...")
    
    # Database schema migration
    try:
        from sqlalchemy import text, inspect
        
        with engine.connect() as conn:
            inspector = inspect(engine)
            
            # Check templates table
            if 'templates' in inspector.get_table_names():
                template_cols = [col['name'] for col in inspector.get_columns('templates')]
                
                if 'name' not in template_cols:
                    logger.info("Adding 'name' column to 'templates'")
                    conn.execute(text("ALTER TABLE templates ADD COLUMN name VARCHAR(100)"))
                    conn.commit()
                
                if 'image_count' not in template_cols:
                    logger.info("Adding 'image_count' column to 'templates'")
                    conn.execute(text("ALTER TABLE templates ADD COLUMN image_count INTEGER DEFAULT 0"))
                    conn.commit()
                
                # Add unique index on name if not exists
                try:
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_templates_name ON templates (name)"))
                    conn.commit()
                except:
                    pass
            
            # Check cameras table
            if 'cameras' in inspector.get_table_names():
                camera_cols = [col['name'] for col in inspector.get_columns('cameras')]
                
                if 'camera_type' not in camera_cols:
                    logger.info("Adding 'camera_type' column to 'cameras'")
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN camera_type VARCHAR(20) DEFAULT 'ip'"))
                    conn.commit()
                
                if 'url' not in camera_cols:
                    logger.info("Adding 'url' column to 'cameras'")
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN url VARCHAR(500)"))
                    conn.commit()
                
                if 'is_active' not in camera_cols:
                    logger.info("Adding 'is_active' column to 'cameras'")
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
                    conn.commit()
                
                if 'last_used' not in camera_cols:
                    logger.info("Adding 'last_used' column to 'cameras'")
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN last_used TIMESTAMP"))
                    conn.commit()
            
            logger.info("✅ Database schema migration completed")
            
    except Exception as e:
        logger.error(f"⚠️ Schema migration error: {e}")
    
    # Start periodic cleanup
    asyncio.create_task(periodic_cleanup())

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down...")
    camera_manager.release_all()

async def periodic_cleanup():
    """Periodic cleanup of old files and resources"""
    while True:
        try:
            cleanup_old_files()
            await asyncio.sleep(3600)  # Every hour
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

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
        pass_count = db.query(InspectionLog).filter(
            InspectionLog.status == "PASS"
        ).count()
        fail_count = db.query(InspectionLog).filter(
            InspectionLog.status == "FAIL"
        ).count()
        
        return StatsResponse(
            total_scans=total_scans,
            pass_count=pass_count,
            fail_count=fail_count
        )
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history", response_model=List[InspectionResponse])
async def get_history(
    limit: int = 100,
    skip: int = 0,
    db: Session = Depends(get_db)
):
    """Get inspection history"""
    try:
        inspections = db.query(InspectionLog)\
            .order_by(InspectionLog.timestamp.desc())\
            .offset(skip)\
            .limit(limit)\
            .all()
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
            .order_by(InspectionLog.timestamp.desc())\
            .all()
        
        return [
            {
                "id": insp.id,
                "timestamp": insp.timestamp.isoformat(),
                "status": insp.status,
                "confidence": insp.confidence,
                "matched_part": insp.matched_part
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
    """Upload template images to HuggingFace Space"""
    try:
        if len(files) < 3 or len(files) > 10:
            raise HTTPException(
                status_code=400,
                detail="Please upload between 3 and 10 template images"
            )
        
        # Process images
        template_images = []
        for file in files:
            contents = await file.read()
            img = Image.open(io.BytesIO(contents))
            
            # Resize for consistency
            img = img.resize((224, 224))
            template_images.append(img)
        
        # Send to HuggingFace Space
        result = await hf_client.save_template(name, template_images)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Failed to save template")
            )
        
        # Save to database
        db_template = Template(
            name=name,
            image_count=len(files),
            created_at=datetime.utcnow()
        )
        db.add(db_template)
        db.commit()
        db.refresh(db_template)
        
        logger.info(f"Template '{name}' created with {len(files)} images")
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
        # Get from HuggingFace
        hf_templates = await hf_client.list_templates()
        
        # Sync with database
        templates = db.query(Template).all()
        
        return [
            {
                "id": t.id,
                "name": t.name,
                "image_count": t.image_count,
                "created_at": t.created_at
            }
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
        
        # Delete from HuggingFace
        await hf_client.delete_template(template.name)
        
        # Delete from database
        db.delete(template)
        db.commit()
        
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
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db)
):
    """Scan uploaded image for defects"""
    try:
        # Read and validate image
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
        
        # Call HuggingFace detection
        result = await hf_client.detect_part(img, threshold)
        
        # Determine status
        status = "PASS" if result.get("matched") else "FAIL"
        
        # Log to database
        log_entry = InspectionLog(
            timestamp=datetime.utcnow(),
            status=status,
            confidence=result.get("confidence", 0.0),
            matched_part=result.get("best_match"),
            source="upload"
        )
        db.add(log_entry)
        db.commit()
        
        logger.info(f"Scan completed: {status} (confidence: {result.get('confidence')})")
        
        return {
            "success": True,
            "status": status,
            "confidence": result.get("confidence"),
            "matched_part": result.get("best_match"),
            "all_results": result.get("all_results", []),
            "log_id": log_entry.id
        }
        
    except Exception as e:
        logger.error(f"Scan error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/capture_and_scan")
async def capture_and_scan(
    camera_id: Optional[int] = 0,
    threshold: float = 0.92,
    db: Session = Depends(get_db)
):
    """Capture from camera and scan"""
    try:
        # Capture frame
        try:
            frame = camera_manager.capture_frame(camera_id)
        except Exception as e:
            logger.error(f"Camera manager capture error: {e}")
            frame = None

        if frame is None:
            # Fallback for environments without physical cameras (like Render)
            if os.getenv("RENDER") or os.getenv("K_SERVICE"):
                return {
                    "success": False, 
                    "error": "Hardware camera not available in this environment. Please use 'Upload Scan' instead.",
                    "status": "N/A"
                }
            raise HTTPException(status_code=500, detail="Failed to capture frame. Ensure camera is connected.")
        
        # Convert to PIL Image
        img = Image.fromarray(frame)
        
        # Detect
        result = await hf_client.detect_part(img, threshold)
        
        status = "PASS" if result.get("matched") else "FAIL"
        
        # Log to database
        log_entry = InspectionLog(
            timestamp=datetime.utcnow(),
            status=status,
            confidence=result.get("confidence", 0.0),
            matched_part=result.get("best_match"),
            source=f"camera_{camera_id}"
        )
        db.add(log_entry)
        db.commit()
        
        return {
            "success": True,
            "status": status,
            "confidence": result.get("confidence"),
            "matched_part": result.get("best_match"),
            "log_id": log_entry.id
        }
        
    except Exception as e:
        logger.error(f"Capture and scan error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CAMERA MANAGEMENT ====================

@app.get("/api/video_feed")
async def video_feed(camera_id: int = 0):
    """Stream video feed from camera"""
    def generate():
        while True:
            try:
                frame = camera_manager.get_frame(camera_id)
                if frame is not None:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                else:
                    break
            except Exception as e:
                logger.error(f"Video feed error: {e}")
                break
    
    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.post("/api/cameras", response_model=CameraResponse)
async def create_camera(camera: CameraCreate, db: Session = Depends(get_db)):
    """Add new camera"""
    try:
        # Test connection
        success = camera_manager.test_camera(camera.url)
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Cannot connect to camera"
            )
        
        db_camera = Camera(
            name=camera.name,
            camera_type=camera.camera_type,
            url=camera.url,
            is_active=True,
            created_at=datetime.utcnow()
        )
        db.add(db_camera)
        db.commit()
        db.refresh(db_camera)
        
        # Add to camera manager
        camera_manager.add_camera(db_camera.id, camera.url)
        
        logger.info(f"Camera '{camera.name}' added successfully")
        return db_camera
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Camera creation error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cameras", response_model=List[CameraResponse])
async def list_cameras(db: Session = Depends(get_db)):
    """List all cameras"""
    try:
        cameras = db.query(Camera).all()
        return cameras
    except Exception as e:
        logger.error(f"Camera list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/cameras/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int,
    camera_update: CameraUpdate,
    db: Session = Depends(get_db)
):
    """Update camera settings"""
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        
        if camera_update.name:
            camera.name = camera_update.name
        if camera_update.url:
            camera.url = camera_update.url
        if camera_update.is_active is not None:
            camera.is_active = camera_update.is_active
        
        db.commit()
        db.refresh(camera)
        return camera
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Camera update error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/cameras/{camera_id}")
async def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    """Delete camera"""
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        
        camera_manager.remove_camera(camera_id)
        db.delete(camera)
        db.commit()
        
        return {"message": "Camera deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Camera deletion error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cameras/test")
async def test_camera_connection(url: str):
    """Test camera connection"""
    try:
        success = camera_manager.test_camera(url)
        return {"success": success}
    except Exception as e:
        logger.error(f"Camera test error: {e}")
        return {"success": False, "error": str(e)}

# ==================== EXPORT ====================

@app.get("/api/export/history")
async def export_history(db: Session = Depends(get_db)):
    """Export history to CSV"""
    try:
        import csv
        from io import StringIO
        
        inspections = db.query(InspectionLog).order_by(
            InspectionLog.timestamp.desc()
        ).all()
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Timestamp", "Status", "Confidence", "Matched Part", "Source"])
        
        for insp in inspections:
            writer.writerow([
                insp.id,
                insp.timestamp.isoformat(),
                insp.status,
                insp.confidence,
                insp.matched_part or "N/A",
                insp.source
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

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}