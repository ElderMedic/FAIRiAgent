"""FastAPI application for the FAIRifier system."""

import os
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ...graph.langgraph_app import FAIRifierLangGraphApp
from ...config import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="FAIRifier API",
    description="Automated FAIR metadata generation system",
    version="1.0.0.20251206rc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global workflow instance
workflow = FAIRifierLangGraphApp()

# In-memory storage for demo (replace with database in production)
projects: Dict[str, Dict[str, Any]] = {}


class ProjectResponse(BaseModel):
    """Response model for project operations."""
    project_id: str
    status: str
    message: str
    confidence_scores: Optional[Dict[str, float]] = None
    needs_review: Optional[bool] = None
    errors: Optional[list] = None


class ProjectStatus(BaseModel):
    """Project status response model."""
    project_id: str
    status: str
    confidence_scores: Dict[str, float]
    needs_review: bool
    errors: list
    artifacts: list
    processing_start: Optional[str] = None
    processing_end: Optional[str] = None


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "FAIRifier API",
        "version": "0.1.0",
        "description": "Automated FAIR metadata generation system"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "0.1.0"
    }


@app.post("/projects/run", response_model=ProjectResponse)
async def run_fairifier(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_name: Optional[str] = None
):
    """
    Upload a document and start the FAIRifier workflow.
    
    Args:
        file: PDF or text document to process
        project_name: Optional project name
    
    Returns:
        Project ID and initial status
    """
    try:
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # Check file size
        file_size = 0
        content = await file.read()
        file_size = len(content)
        
        if file_size > config.max_document_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413, 
                detail=f"File too large. Max size: {config.max_document_size_mb}MB"
            )
        
        # Save uploaded file temporarily
        suffix = Path(file.filename).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        # Generate project ID
        project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Store project info
        projects[project_id] = {
            "project_id": project_id,
            "project_name": project_name or file.filename,
            "filename": file.filename,
            "file_path": tmp_path,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "file_size": file_size
        }
        
        # Start workflow in background
        background_tasks.add_task(run_workflow_background, project_id, tmp_path)
        
        logger.info(f"Started project {project_id} for file {file.filename}")
        
        return ProjectResponse(
            project_id=project_id,
            status="pending",
            message=f"Project {project_id} started successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start project: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start project: {str(e)}")


async def run_workflow_background(project_id: str, file_path: str):
    """Run workflow in background."""
    try:
        logger.info(f"Running workflow for project {project_id}")
        
        # Update status
        projects[project_id]["status"] = "running"
        
        # Run workflow
        result = await workflow.run(file_path, project_id)
        
        # Update project with results
        projects[project_id].update({
            "status": result.get("status", "completed"),
            "confidence_scores": result.get("confidence_scores", {}),
            "needs_review": result.get("needs_human_review", False),
            "errors": result.get("errors", []),
            "artifacts": result.get("artifacts", {}),
            "processing_end": result.get("processing_end"),
            "result": result
        })
        
        logger.info(f"Workflow completed for project {project_id}")
        
    except Exception as e:
        logger.error(f"Workflow failed for project {project_id}: {str(e)}")
        projects[project_id].update({
            "status": "failed",
            "errors": [str(e)]
        })
    finally:
        # Clean up temporary file
        try:
            os.unlink(file_path)
        except:
            pass


@app.get("/projects/{project_id}/status", response_model=ProjectStatus)
async def get_project_status(project_id: str):
    """
    Get status of a FAIRifier project.
    
    Args:
        project_id: Project identifier
    
    Returns:
        Current project status and results
    """
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects[project_id]
    
    return ProjectStatus(
        project_id=project_id,
        status=project.get("status", "unknown"),
        confidence_scores=project.get("confidence_scores", {}),
        needs_review=project.get("needs_review", False),
        errors=project.get("errors", []),
        artifacts=list(project.get("artifacts", {}).keys()),
        processing_start=project.get("created_at"),
        processing_end=project.get("processing_end")
    )


@app.get("/projects")
async def list_projects():
    """List all projects."""
    project_list = []
    for project_id, project in projects.items():
        project_list.append({
            "project_id": project_id,
            "project_name": project.get("project_name"),
            "filename": project.get("filename"),
            "status": project.get("status"),
            "created_at": project.get("created_at"),
            "needs_review": project.get("needs_review", False)
        })
    
    return {"projects": project_list}


@app.get("/projects/{project_id}/artifacts/{artifact_name}")
async def get_project_artifact(project_id: str, artifact_name: str):
    """
    Download a specific artifact from a project.
    
    Args:
        project_id: Project identifier
        artifact_name: Name of the artifact (template_schema, template_yaml, rdf_turtle, etc.)
    
    Returns:
        File content
    """
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects[project_id]
    artifacts = project.get("artifacts", {})
    
    if artifact_name not in artifacts:
        raise HTTPException(status_code=404, detail="Artifact not found")
    
    content = artifacts[artifact_name]
    
    # Determine content type and filename
    content_types = {
        "template_schema": ("application/json", "template.schema.json"),
        "template_yaml": ("application/yaml", "template.yaml"),
        "rdf_turtle": ("text/turtle", "metadata.ttl"),
        "rdf_jsonld": ("application/ld+json", "metadata.jsonld"),
        "ro_crate": ("application/json", "ro-crate-metadata.json"),
        "validation_report": ("text/plain", "validation_report.txt")
    }
    
    content_type, filename = content_types.get(artifact_name, ("text/plain", f"{artifact_name}.txt"))
    
    # Create temporary file for download
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=f"_{filename}") as tmp_file:
        tmp_file.write(content)
        tmp_path = tmp_file.name
    
    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type=content_type,
        background=BackgroundTasks().add_task(lambda: os.unlink(tmp_path))
    )


@app.get("/projects/{project_id}/artifacts")
async def list_project_artifacts(project_id: str):
    """List available artifacts for a project."""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects[project_id]
    artifacts = project.get("artifacts", {})
    
    artifact_list = []
    for name, content in artifacts.items():
        artifact_list.append({
            "name": name,
            "size": len(content) if content else 0,
            "available": bool(content)
        })
    
    return {
        "project_id": project_id,
        "artifacts": artifact_list
    }


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project and its artifacts."""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    del projects[project_id]
    
    return {"message": f"Project {project_id} deleted successfully"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
