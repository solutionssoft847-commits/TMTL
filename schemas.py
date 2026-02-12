from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class InspectionCreate(BaseModel):
    status: str
    confidence: float
    matched_part: Optional[str] = None
    source: str

class InspectionResponse(BaseModel):
    id: int
    timestamp: datetime
    status: str
    confidence: float
    matched_part: Optional[str]
    source: str
    
    class Config:
        from_attributes = True

class TemplateCreate(BaseModel):
    name: str

class TemplateResponse(BaseModel):
    id: int
    name: str
    image_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class CameraCreate(BaseModel):
    name: str
    camera_type: str
    url: str

class CameraUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    is_active: Optional[bool] = None

class CameraResponse(BaseModel):
    id: int
    name: str
    camera_type: str
    url: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class StatsResponse(BaseModel):
    total_scans: int
    pass_count: int
    fail_count: int