"""
Mail Merge Placeholder System - Backend API
Demo standalone FastAPI application
"""
import os
import uuid
from pathlib import Path
from typing import Dict
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from mail_merge_processor import MailMergeProcessor
from merge_executor import MergeExecutor
from gemini_client import GeminiClient

# Load environment variables
load_dotenv()

# Setup paths
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATE_DIR = UPLOAD_DIR / "templates"
RESULT_DIR = UPLOAD_DIR / "results"

# Ensure directories exist
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# Configuration
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize FastAPI
app = FastAPI(
    title="Mail Merge Placeholder System",
    description="Convert Word documents with placeholders to Mail Merge templates",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For demo - restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Mail Merge Placeholder System",
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Mail Merge Placeholder System API",
        "endpoints": {
            "health": "GET /health",
            "convert": "POST /convert",
            "merge": "POST /merge",
            "download": "GET /download/{file_id}"
        }
    }


@app.post("/convert")
async def convert_to_template(file: UploadFile = File(...)):
    """Upload .docx and convert to Mail Merge template

    Args:
        file: Uploaded .docx file

    Returns:
        JSON with template_id and list of detected fields
    """
    # Validate file type
    if not file.filename.endswith('.docx'):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024)}MB"
        )

    # Save uploaded file temporarily
    temp_path = UPLOAD_DIR / f"temp_{file.filename}"
    try:
        with open(temp_path, "wb") as f:
            f.write(content)

        # Process document with SmartMailMergeConverter (no API key needed)
        processor = MailMergeProcessor()
        template_id = str(uuid.uuid4())
        output_path = TEMPLATE_DIR / f"{template_id}.docx"
        result = processor.convert_to_mail_merge(str(temp_path), str(output_path))

        # Build response
        response_data = {
            "template_id": result["template_id"],
            "fields": result["fields"],
            "field_count": result["field_count"],
            "html_preview": result.get("html_preview", ""),
            "download_url": f"/download/{result['template_id']}",
            "method": result.get("method", "smart_converter")
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")
    finally:
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()


@app.post("/merge")
async def merge_template(
    template_id: str = Form(...),
    context: str = Form(...)
):
    """Fill Mail Merge template with context data

    Args:
        template_id: ID of template from /convert endpoint
        context: Text context with data to fill

    Returns:
        JSON with result_id and download_url
    """
    # Find template
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    try:
        # Parse context with Gemini to extract structured data
        if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
            raise HTTPException(
                status_code=500,
                detail="GEMINI_API_KEY not configured. Please set it in .env file"
            )

        gemini_client = GeminiClient(GEMINI_API_KEY)

        # Get template fields first
        executor = MergeExecutor()
        template_fields = executor.get_template_fields(str(template_path))

        # Extract data from context using Gemini
        data = _extract_data_from_context(
            gemini_client,
            context,
            template_fields
        )

        # Execute merge
        result_path, result_id = executor.execute_merge(str(template_path), data)

        return JSONResponse(content={
            "result_id": result_id,
            "download_url": f"/download/{result_id}",
            "fields_filled": len(data)
        })

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Merge failed: {str(e)}")


@app.get("/download/{file_id}")
async def download_file(file_id: str):
    """Download template or result file

    Args:
        file_id: ID of template or result file

    Returns:
        .docx file download
    """
    # Check templates
    template_path = TEMPLATE_DIR / f"{file_id}.docx"
    if template_path.exists():
        return FileResponse(
            path=str(template_path),
            filename=f"template_{file_id}.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    # Check results
    result_path = RESULT_DIR / f"{file_id}.docx"
    if result_path.exists():
        return FileResponse(
            path=str(result_path),
            filename=f"document_{file_id}.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    raise HTTPException(status_code=404, detail="File not found")


def _extract_data_from_context(
    gemini_client: GeminiClient,
    context: str,
    template_fields: list
) -> Dict[str, str]:
    """Extract structured data from context using Gemini

    Args:
        gemini_client: Gemini client instance
        context: User-provided context text
        template_fields: List of required field names

    Returns:
        Dict mapping field names to values
    """
    prompt = f"""Extract data from this Vietnamese text for a mail merge template.

Required fields: {', '.join(template_fields)}

Context: {context}

Return a JSON object with field names as keys and extracted values as values.
Example: {{"ho_ten": "Nguyen Van A", "so_cmnd": "123456789"}}

JSON:"""

    try:
        response = gemini_client.model.generate_content(prompt)

        # Parse JSON response
        import json
        response_text = response.text.strip()

        # Try to extract JSON if there's extra text
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        data = json.loads(response_text)

        # Ensure all required fields are present
        # If missing, use empty string as default
        for field in template_fields:
            if field not in data:
                data[field] = ""

        return data

    except Exception as e:
        # Fallback: return empty values for all fields
        return {field: "" for field in template_fields}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
