from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
from .database import Base

class InspectionLog(Base):
    __tablename__ = "inspection_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20))  # PERFECT or DEFECTIVE
    confidence = Column(Float)
    matched_part = Column(String(100), nullable=True)
    source = Column(String(50))  # upload, camera_0, etc.
    
    def __repr__(self):
        return f"<InspectionLog(id={self.id}, status={self.status})>"

class Template(Base):
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True)
    image_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<Template(name={self.name})>"

class Camera(Base):
    __tablename__ = "cameras"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    camera_type = Column(String(20))  # ip or usb
    url = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f"<Camera(name={self.name})>"