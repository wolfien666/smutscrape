from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ScrapeRequest(BaseModel):
    command: str = Field(..., description="Full CLI command")
    overwrite: bool = False
    re_nfo: bool = False
    page: str = "1"
    applystate: bool = False
    debug: bool = False

class ScrapeResponse(BaseModel):
    success: bool
    message: str
    task_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    errors: Optional[List[str]] = None

class TaskStatus(BaseModel):
    task_id: str
    status: str  # "pending", "running", "completed", "failed"
    message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

class SiteInfo(BaseModel):
    code: str
    name: str
    domain: str
    modes: List[Dict[str, Any]]
    metadata: List[str]
    requires_selenium: bool
    notes: Optional[List[str]] = None 