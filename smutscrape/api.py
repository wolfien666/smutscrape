#!/usr/bin/env python3
"""
Smutscrape API Server Module

This module provides a FastAPI-based REST API for the smutscrape application,
allowing remote execution of scraping commands and task management.
"""

import json
import uuid
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

# FastAPI imports
try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.responses import JSONResponse, StreamingResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from loguru import logger

# These will be imported from the main scrape module
from scrape import (
    load_configuration,
    get_session_manager,
    is_url,
    process_url,
    process_fallback_download,
    handle_multi_arg,
    handle_vpn,
    cleanup,
    get_available_modes,
    has_metadata_selectors,
    SITE_DIR,
    SELENIUM_AVAILABLE
)
from downloaders import DownloadManager
from sites import SiteManager, SiteConfiguration


# Pydantic models for API requests/responses
class ScrapeRequest(BaseModel):
    """Request model for scraping commands"""
    command: str = Field(..., description="Full command as you would type in CLI (e.g., 'ph pornstar \"Massy Sweet\"')")
    overwrite: bool = Field(False, description="Overwrite existing files")
    re_nfo: bool = Field(False, description="Regenerate .nfo files")
    page: str = Field("1", description="Page to start from (e.g., '12.9' for page 12, video 9)")
    applystate: bool = Field(False, description="Add URLs to .state if file exists")
    debug: bool = Field(False, description="Enable debug logging")


class ScrapeResponse(BaseModel):
    """Response model for scraping operations"""
    success: bool
    message: str
    task_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    errors: Optional[List[str]] = None


class TaskStatus(BaseModel):
    """Response model for task status queries"""
    task_id: str
    status: str  # "pending", "running", "completed", "failed"
    message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class SiteInfo(BaseModel):
    """Response model for site information"""
    code: str
    name: str
    domain: str
    modes: List[Dict[str, Any]]
    metadata: List[str]
    requires_selenium: bool
    notes: Optional[List[str]] = None


# Create FastAPI app
app = FastAPI(
    title="Smutscrape API",
    description="API for scraping and downloading adult content with metadata",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Thread executor for running blocking operations
executor = ThreadPoolExecutor(max_workers=4)

# Task tracking
active_tasks = OrderedDict()  # task_id -> task_info
task_lock = threading.Lock()
MAX_TASK_HISTORY = 100  # Keep last 100 tasks in memory


@app.options("/scrape")
async def options_scrape():
    return {}


@app.get("/", response_model=Dict[str, Any])
async def root():
    """Root endpoint providing API information"""
    return {
        "name": "Smutscrape API",
        "version": "1.0.0",
        "description": "API for scraping and downloading adult content with metadata",
        "endpoints": {
            "/": "This information page",
            "/sites": "List all supported sites",
            "/sites/{code}": "Get detailed information about a specific site",
            "/scrape": "Execute a scrape command (returns immediately with task_id)",
            "/tasks/{task_id}": "Get status of a specific task",
            "/tasks": "List all tasks (optional: ?status=pending/running/completed/failed)"
        },
        "notes": [
            "POST /scrape returns immediately with a task_id",
            "Use GET /tasks/{task_id} to check progress",
            "Multiple scraping tasks can run concurrently"
        ]
    }


@app.get("/sites", response_model=List[SiteInfo])
async def get_sites():
    """Get list of all supported sites"""
    # Use the global site manager
    from scrape import site_manager
    
    sites = []
    for site_config in site_manager.get_all_sites():
        modes_list = []
        for mode in site_config.modes.values():
            modes_list.append({
                "name": mode.name,
                "description": mode.tip,
                "supports_pagination": mode.supports_pagination(),
                "examples": mode.examples
            })
        
        notes = []
        if site_config.note:
            notes.append(site_config.note)
        if site_config.name_suffix:
            notes.append(f"Filenames are appended with '{site_config.name_suffix}'")
        if site_config.unique_name:
            notes.append("Filenames include UID to avoid collisions")
        
        site_info = SiteInfo(
            code=site_config.shortcode,
            name=site_config.name,
            domain=site_config.domain,
            modes=modes_list,
            metadata=site_config.get_metadata_fields(),
            requires_selenium=site_config.use_selenium,
            notes=notes if notes else None
        )
        sites.append(site_info)
    
    return sorted(sites, key=lambda x: x.code)


@app.get("/sites/{code}", response_model=SiteInfo)
async def get_site(code: str):
    """Get detailed information about a specific site"""
    from scrape import site_manager
    
    site_config = site_manager.get_site_by_identifier(code)
    if not site_config:
        raise HTTPException(status_code=404, detail=f"Site '{code}' not found")
    
    modes_list = []
    for mode in site_config.modes.values():
        modes_list.append({
            "name": mode.name,
            "description": mode.tip,
            "supports_pagination": mode.supports_pagination(),
            "examples": mode.examples
        })
    
    notes = []
    if site_config.note:
        notes.append(site_config.note)
    if site_config.name_suffix:
        notes.append(f"Filenames are appended with '{site_config.name_suffix}'")
    if site_config.unique_name:
        notes.append("Filenames include UID to avoid collisions")
    
    return SiteInfo(
        code=site_config.shortcode,
        name=site_config.name,
        domain=site_config.domain,
        modes=modes_list,
        metadata=site_config.get_metadata_fields(),
        requires_selenium=site_config.use_selenium,
        notes=notes if notes else None
    )


def run_scrape_command(command: str, overwrite: bool = False, re_nfo: bool = False, 
                      page: str = "1", applystate: bool = False, debug: bool = False):
    """Execute a scrape command in a thread"""
    import shlex
    import sys
    
    # Parse the command string
    try:
        command_parts = shlex.split(command)
    except ValueError as e:
        return {"success": False, "message": f"Invalid command format: {e}"}
    
    # Create a mock args object
    class MockArgs:
        def __init__(self):
            self.args = command_parts
            self.overwrite = overwrite
            self.re_nfo = re_nfo
            self.page = page
            self.applystate = applystate
            self.debug = debug
            self.table = None
            # Parse page into page_num and video_offset
            page_parts = page.split('.')
            self.page_num = int(page_parts[0])
            self.video_offset = int(page_parts[1]) if len(page_parts) > 1 else 0
    
    mock_args = MockArgs()
    
    # Setup logging for this request
    if debug:
        logger.add(
            sys.stderr,
            level="DEBUG",
            format="<d>{time:YYYYMMDDHHmmss.SSS}</d> | <d>{level:1.1}</d> | <d>{function}:{line}</d> · <d>{message}</d>",
            colorize=True,
            filter=lambda record: record["level"].name == "DEBUG"
        )
    
    try:
        # Load configurations
        general_config = load_configuration('general')
        if not general_config:
            return {"success": False, "message": "Failed to load general configuration"}
        
        # Initialize download manager
        import scrape
        if not hasattr(scrape, 'download_manager') or scrape.download_manager is None:
            scrape.download_manager = DownloadManager(general_config)
        
        # Load state
        state_set = get_session_manager().processed_urls
        
        # Process the command
        if len(command_parts) == 1:
            # Single argument (URL or site code)
            arg = command_parts[0]
            is_url_flag = is_url(arg)
            config = load_configuration('site', arg)
            
            if config:
                if is_url_flag:
                    if config.get('use_selenium', False) and not SELENIUM_AVAILABLE:
                        return {
                            "success": False,
                            "message": f"Site requires Selenium, which is not available on this system"
                        }
                    process_url(arg, config, general_config, mock_args.overwrite, 
                               mock_args.re_nfo, mock_args.page, apply_state=mock_args.applystate, 
                               state_set=state_set)
                    return {"success": True, "message": f"Successfully processed URL: {arg}"}
                else:
                    # Just site code - return site info
                    return {
                        "success": False,
                        "message": f"Please specify a mode and query for site '{arg}'"
                    }
            else:
                if is_url_flag:
                    # Fallback download
                    success = process_fallback_download(arg, general_config, mock_args.overwrite)
                    return {
                        "success": success,
                        "message": f"{'Successfully' if success else 'Failed to'} process URL with fallback downloader"
                    }
                else:
                    return {"success": False, "message": f"Unknown site or invalid URL: {arg}"}
        
        elif len(command_parts) >= 2:
            # Multi-argument command
            handle_multi_arg(command_parts, general_config, mock_args, state_set)
            return {
                "success": True,
                "message": f"Successfully executed: {' '.join(command_parts)}"
            }
        else:
            return {"success": False, "message": "Invalid command format"}
        
    except SystemExit as e:
        # Catch sys.exit() calls and convert to API response
        return {
            "success": False,
            "message": f"Command failed with exit code: {e.code}"
        }
    except Exception as e:
        logger.error(f"API command execution error: {e}", exc_info=debug)
        return {
            "success": False,
            "message": f"Error executing command: {str(e)}"
        }
    finally:
        # Cleanup
        handle_vpn(general_config, 'stop')
        cleanup(general_config)


def validate_and_prepare_command(command: str, overwrite: bool = False, re_nfo: bool = False, 
                                 page: str = "1", applystate: bool = False, debug: bool = False):
    """Validate command before executing - returns (is_valid, message, command_parts)"""
    import shlex
    
    try:
        command_parts = shlex.split(command)
    except ValueError as e:
        return False, f"Invalid command format: {e}", None
    
    if not command_parts:
        return False, "Empty command", None
    
    # Quick validation of command structure
    if len(command_parts) == 1:
        arg = command_parts[0]
        is_url_flag = is_url(arg)
        
        if not is_url_flag:
            # Check if it's a valid site code
            config = load_configuration('site', arg)
            if config:
                return False, f"Please specify a mode and query for site '{arg}'", None
            else:
                return False, f"Unknown site: {arg}", None
    
    elif len(command_parts) >= 2:
        # Check if site exists
        site_config = load_configuration('site', command_parts[0])
        if not site_config:
            return False, f"Site '{command_parts[0]}' not found", None
        
        # Check if mode is valid
        mode = command_parts[1]
        if mode not in site_config.get('modes', {}):
            available_modes = get_available_modes(site_config)
            return False, f"Invalid mode '{mode}' for site '{command_parts[0]}'. Available modes: {', '.join(available_modes)}", None
        
        # Check selenium availability if required
        if site_config.get('use_selenium', False) and not SELENIUM_AVAILABLE:
            return False, f"Site '{command_parts[0]}' requires Selenium, which is not available", None
    
    return True, "Command validated", command_parts


def run_scrape_task(task_id: str, command: str, overwrite: bool, re_nfo: bool, 
                   page: str, applystate: bool, debug: bool):
    """Execute scraping task and update task status"""
    with task_lock:
        if task_id in active_tasks:
            active_tasks[task_id]["status"] = "running"
            active_tasks[task_id]["started_at"] = datetime.now().isoformat()
    
    try:
        result = run_scrape_command(command, overwrite, re_nfo, page, applystate, debug)
        
        with task_lock:
            if task_id in active_tasks:
                active_tasks[task_id]["status"] = "completed" if result["success"] else "failed"
                active_tasks[task_id]["message"] = result["message"]
                active_tasks[task_id]["completed_at"] = datetime.now().isoformat()
                
                # Clean up old tasks if we have too many
                if len(active_tasks) > MAX_TASK_HISTORY:
                    # Remove oldest completed tasks
                    to_remove = []
                    for tid, info in active_tasks.items():
                        if info["status"] in ["completed", "failed"] and len(to_remove) < 10:
                            to_remove.append(tid)
                    for tid in to_remove:
                        del active_tasks[tid]
    
    except Exception as e:
        with task_lock:
            if task_id in active_tasks:
                active_tasks[task_id]["status"] = "failed"
                active_tasks[task_id]["message"] = f"Unexpected error: {str(e)}"
                active_tasks[task_id]["completed_at"] = datetime.now().isoformat()


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """Execute a scrape command"""
    # Validate command first
    is_valid, message, command_parts = validate_and_prepare_command(
        request.command, request.overwrite, request.re_nfo, 
        request.page, request.applystate, request.debug
    )
    
    if not is_valid:
        return ScrapeResponse(
            success=False,
            message=message,
            errors=[message]
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Create task record
    with task_lock:
        active_tasks[task_id] = {
            "task_id": task_id,
            "command": request.command,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "message": None
        }
    
    # Add to background tasks
    background_tasks.add_task(
        run_scrape_task,
        task_id,
        request.command,
        request.overwrite,
        request.re_nfo,
        request.page,
        request.applystate,
        request.debug
    )
    
    return ScrapeResponse(
        success=True,
        message=f"Scraping task started successfully",
        task_id=task_id,
        details={"command": request.command, "task_id": task_id}
    )


@app.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Get the status of a scraping task"""
    with task_lock:
        if task_id not in active_tasks:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        task_info = active_tasks[task_id]
        return TaskStatus(
            task_id=task_info["task_id"],
            status=task_info["status"],
            message=task_info.get("message"),
            created_at=task_info["created_at"],
            started_at=task_info.get("started_at"),
            completed_at=task_info.get("completed_at")
        )


@app.get("/tasks", response_model=List[TaskStatus])
async def list_tasks(status: Optional[str] = None):
    """List all tasks, optionally filtered by status"""
    with task_lock:
        tasks = []
        for task_info in active_tasks.values():
            if status is None or task_info["status"] == status:
                tasks.append(TaskStatus(
                    task_id=task_info["task_id"],
                    status=task_info["status"],
                    message=task_info.get("message"),
                    created_at=task_info["created_at"],
                    started_at=task_info.get("started_at"),
                    completed_at=task_info.get("completed_at")
                ))
        return tasks


def run_api_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the FastAPI server"""
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI is not installed. Please install it with: pip install fastapi uvicorn")
    
    logger.info(f"Starting Smutscrape API server on {host}:{port}")
    uvicorn.run(app, host=host, port=port) 