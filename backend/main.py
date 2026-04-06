"""
Mail Merge Placeholder System - Backend API
Demo standalone FastAPI application
"""
import os
import re
import uuid
from pathlib import Path
from typing import Dict
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
import json
from docx import Document
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
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

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
        "status": "OK"
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

        # Debug: Log HTML preview content
        html_preview = result.get("html_preview", "")
        print(f"=== HTML PREVIEW DEBUG ===")
        print(f"Fields detected: {result['fields']}")
        print(f"HTML preview length: {len(html_preview)}")
        print(f"Contains mail-merge-placeholder: {'mail-merge-placeholder' in html_preview}")
        print(f"=== END DEBUG ===")

        # Build response
        response_data = {
            "template_id": result["template_id"],
            "fields": result["fields"],
            "field_count": result["field_count"],
            "html_preview": html_preview,
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
    context: str = Form(None),
    field_values: str = Form(None),
    active_fields: str = Form(None)
):
    """Fill Mail Merge template with data

    Args:
        template_id: ID of template from /convert endpoint
        context: Text context with data to fill (optional, for Gemini extraction)
        field_values: JSON string of field-value pairs (optional, for direct values)
        active_fields: JSON string array of active fields to be filled


    Returns:
        JSON with result_id and download_url
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    try:
        executor = MergeExecutor()
        template_fields = executor.get_template_fields(str(template_path))

        # Determine data source
        if field_values:
            data = json.loads(field_values)

            # Ensure all required fields have values (empty string if missing)
            for field in template_fields:
                if field not in data:
                    data[field] = ""

        elif context:
            # Use Gemini to extract from context
            if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
                raise HTTPException(
                    status_code=500,
                    detail="GEMINI_API_KEY not configured. Please set it in .env file"
                )

            gemini_client = GeminiClient(GEMINI_API_KEY)
            
            if active_fields:
                active_f = set(json.loads(active_fields))
                template_fields = [f for f in template_fields if f in active_f]

            data = _extract_data_from_context(
                gemini_client,
                context,
                template_fields
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Either 'context' or 'field_values' must be provided"
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
    # Folders to search: (Path, filename_prefix)
    search_folders = [
        (TEMPLATE_DIR, "template_"),
        (RESULT_DIR, "document_")
    ]

    for directory, prefix in search_folders:
        file_path = directory / f"{file_id}.docx"
        if file_path.exists():
            return FileResponse(
                path=str(file_path),
                filename=f"{prefix}{file_id}.docx",
                media_type=DOCX_MEDIA_TYPE
            )

    raise HTTPException(status_code=404, detail="File not found")


@app.get("/preview/{result_id}")
async def preview_result(result_id: str):
    """Get HTML preview of merged result

    Args:
        result_id: ID of result file

    Returns:
        JSON with html_preview
    """
    # Find result file
    result_path = RESULT_DIR / f"{result_id}.docx"
    if not result_path.exists():
        raise HTTPException(status_code=404, detail=f"Result not found: {result_id}")

    try:
        # Generate HTML preview
        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(result_path), [])

        return JSONResponse(content={
            "result_id": result_id,
            "html_preview": html_preview
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


@app.post("/update-template")
async def update_template(template_id: str = Form(...), rename_map: str = Form(...), editor_html: str = Form(None)):
    """Update template fields directly in DOCX using XPath for efficiency"""
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        rename_mapping = json.loads(rename_map)
        doc = Document(str(template_path))
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        flds = [f for f in doc.element.iter(f"{w_ns}fldSimple") if "MERGEFIELD" in f.get(f"{w_ns}instr", "")]

        count_updated = 0
        count_deleted = 0
        for fld in flds:
            instr = fld.get(f"{w_ns}instr", "")
            match = re.search(r'MERGEFIELD\s+(\S+)', instr)
            if match:
                current_name = match.group(1)
                new_name = rename_mapping.get(current_name)
                
                if new_name is not None and new_name != current_name:
                    # Keep the original \z part
                    z_match = re.search(r'\\z\s*"([^"]*)"', instr)
                    z_part = f' \\z "{z_match.group(1)}"' if z_match else ""

                    fld.set(f"{w_ns}instr", f' MERGEFIELD {new_name} \\* MERGEFORMAT{z_part} ')
                    for t in fld.iter(f"{w_ns}t"):
                        t.text = f"«{new_name}»"
                    count_updated += 1
                elif new_name is None:
                    count_deleted += 1
                    # It was deleted by the user. DO NOT remove it from DOCX
                    # We just leave it as is so it falls back to \z

        doc.save(str(template_path))
        return {"template_id": template_id, "updated": True, 
                "fields_updated": count_updated, "fields_deleted": count_deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
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
