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

        # Debug: Log HTML preview content
        html_preview = result.get("html_preview", "")
        print(f"=== HTML PREVIEW DEBUG ===")
        print(f"Fields detected: {result['fields']}")
        print(f"HTML preview length: {len(html_preview)}")
        print(f"Contains « characters: {'«' in html_preview}")
        print(f"Contains mail-merge-placeholder: {'mail-merge-placeholder' in html_preview}")
        # Print first 1000 chars
        print(f"First 1000 chars:\n{html_preview[:1000]}")
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
    field_values: str = Form(None)
):
    """Fill Mail Merge template with data

    Args:
        template_id: ID of template from /convert endpoint
        context: Text context with data to fill (optional, for Gemini extraction)
        field_values: JSON string of field-value pairs (optional, for direct values)

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
            # Use direct field values
            import json
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
async def update_template(
    template_id: str = Form(...),
    fields: str = Form(...),
    editor_html: str = Form(None)
):
    """Update template field names by renaming MERGEFIELD fields directly in DOCX
    DELETES extra fields if user removed placeholders

    Args:
        template_id: ID of template to update
        fields: JSON string of field names
        editor_html: Not used

    Returns:
        JSON with updated template_id and fields
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    try:
        import json
        from docx import Document

        # Parse new field names
        new_fields = json.loads(fields)

        # Load template
        doc = Document(str(template_path))

        # Find all MERGEFIELD fields and process them (rename or delete)
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

        # Collect all fldSimple elements with their parents
        fields_to_process = []

        for para in doc.paragraphs:
            for element in para._p.iter():
                if element.tag == f"{w_ns}fldSimple":
                    instr = element.get(f"{w_ns}instr", "")
                    if "MERGEFIELD" in instr:
                        fields_to_process.append((element, para._p))

        # Process tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for element in para._p.iter():
                            if element.tag == f"{w_ns}fldSimple":
                                instr = element.get(f"{w_ns}instr", "")
                                if "MERGEFIELD" in instr:
                                    fields_to_process.append((element, para._p))

        # Process fields: rename or delete
        for idx, (fld_element, parent) in enumerate(fields_to_process):
            if idx < len(new_fields):
                # Rename existing field
                new_name = new_fields[idx]
                fld_element.set(f"{w_ns}instr", f' MERGEFIELD {new_name} \\* MERGEFORMAT ')

                # Update the display text «fieldName»
                nested_run = fld_element.find(f"{w_ns}r")
                if nested_run is not None:
                    t_elem = nested_run.find(f"{w_ns}t")
                    if t_elem is not None:
                        t_elem.text = f"«{new_name}»"
            else:
                # DELETE extra fields that user removed
                parent.remove(fld_element)

        # Save updated template
        doc.save(str(template_path))

        return JSONResponse(content={
            "template_id": template_id,
            "fields": new_fields,
            "updated": True,
            "fields_updated": len(new_fields),
            "fields_deleted": len(fields_to_process) - len(new_fields)
        })

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}\n{traceback.format_exc()}")
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
