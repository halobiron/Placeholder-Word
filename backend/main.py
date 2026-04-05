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
        original_backup_path = TEMPLATE_DIR / f"{template_id}_original.docx"
        result = processor.convert_to_mail_merge(str(temp_path), str(output_path))

        # Backup original converted DOCX (before any user modifications)
        import shutil
        shutil.copy(str(output_path), str(original_backup_path))

        # Save initial field mapping
        field_mapping_path = TEMPLATE_DIR / f"{template_id}_fields.json"
        with open(field_mapping_path, 'w', encoding='utf-8') as f:
            import json
            json.dump({
                "fields": result["fields"],
                "original_fields": result["fields"],
                "has_modifications": False
            }, f, ensure_ascii=False, indent=2)

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
    """Fill Mail Merge template with data (preserves original formatting)

    Args:
        template_id: ID of template from /convert endpoint
        context: Text context with data to fill (optional, for Gemini extraction)
        field_values: JSON string of field-value pairs (optional, for direct values)

    Returns:
        JSON with result_id and download_url
    """
    # Check for field mapping to determine which template to use
    field_mapping_path = TEMPLATE_DIR / f"{template_id}_fields.json"
    original_backup_path = TEMPLATE_DIR / f"{template_id}_original.docx"

    # Determine which template to use
    template_to_use = None
    field_mapping = None

    if field_mapping_path.exists() and original_backup_path.exists():
        # Load field mapping
        import json
        with open(field_mapping_path, 'r', encoding='utf-8') as f:
            field_mapping = json.load(f)

        # If fields were modified, use original template
        if field_mapping.get('has_modifications', False):
            template_to_use = original_backup_path
        else:
            template_to_use = TEMPLATE_DIR / f"{template_id}.docx"
    else:
        # No mapping found, use regular template
        template_to_use = TEMPLATE_DIR / f"{template_id}.docx"

    if not template_to_use.exists():
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    try:
        executor = MergeExecutor()
        template_fields = executor.get_template_fields(str(template_to_use))

        print(f"=== MERGE DEBUG ===")
        print(f"Template to use: {template_to_use}")
        print(f"Template fields from DOCX: {template_fields}")
        if field_mapping:
            print(f"Field mapping - original: {field_mapping.get('original_fields', [])}")
            print(f"Field mapping - current: {field_mapping.get('fields', [])}")
            print(f"Has modifications: {field_mapping.get('has_modifications', False)}")
        print(f"===================")

        # Determine data source
        if field_values:
            # Use direct field values
            import json
            data = json.loads(field_values)

            # If field mapping exists, map current field names to template field names
            if field_mapping and field_mapping.get('has_modifications', False):
                original_fields = field_mapping.get('original_fields', [])
                current_fields = field_mapping.get('fields', [])

                # Create bidirectional mapping:
                # - current_name -> original_name (for renamed fields)
                # - original_name -> current_name (for filling data)
                field_name_map = {}
                for i, current_name in enumerate(current_fields):
                    if i < len(original_fields):
                        field_name_map[current_name] = original_fields[i]

                # Build data with original field names
                # Only fill fields that exist in the template
                final_data = {}
                for current_name, value in data.items():
                    if current_name in field_name_map:
                        original_name = field_name_map[current_name]
                        # Only include if this field exists in current template
                        if original_name in template_fields:
                            final_data[original_name] = value

                data = final_data
            else:
                # No modifications - filter data to only include fields in template
                data = {k: v for k, v in data.items() if k in template_fields}

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

            # If field mapping exists, extract with current field names then remap to template fields
            if field_mapping and field_mapping.get('has_modifications', False):
                current_fields = field_mapping.get('fields', [])
                original_fields = field_mapping.get('original_fields', [])

                print(f"Extracting with current fields: {current_fields}")
                data = _extract_data_from_context(
                    gemini_client,
                    context,
                    current_fields
                )
                print(f"Data extracted from Gemini: {data}")

                # Build mapping: current_name -> original_name
                field_name_map = {}
                for i, current_name in enumerate(current_fields):
                    if i < len(original_fields):
                        field_name_map[current_name] = original_fields[i]

                print(f"Field name mapping: {field_name_map}")

                # Map to original field names, but only keep fields that exist in template
                remapped_data = {}
                for current_name, value in data.items():
                    if current_name in field_name_map:
                        original_name = field_name_map[current_name]
                        # Only include if this field exists in current template
                        if original_name in template_fields:
                            remapped_data[original_name] = value

                print(f"Data after remapping: {remapped_data}")
                data = remapped_data
            else:
                # No modifications, use template fields directly
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

        # Execute merge with the appropriate template
        result_path, result_id = executor.execute_merge(str(template_to_use), data)

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
    """Update template by regenerating DOCX from HTML editor (preserves formatting)

    Args:
        template_id: ID of template to update
        fields: JSON string of current field names after editing
        editor_html: HTML content from edited preview (used to regenerate DOCX)

    Returns:
        JSON with updated template_id and fields
    """
    # Find files
    field_mapping_path = TEMPLATE_DIR / f"{template_id}_fields.json"
    original_backup_path = TEMPLATE_DIR / f"{template_id}_original.docx"
    template_path = TEMPLATE_DIR / f"{template_id}.docx"

    if not field_mapping_path.exists() or not original_backup_path.exists():
        raise HTTPException(status_code=404, detail=f"Template files not found: {template_id}")

    if not editor_html:
        raise HTTPException(status_code=400, detail="editor_html is required to regenerate template")

    try:
        import json
        from smart_mail_merge_converter import SmartMailMergeConverter

        # Parse current fields
        current_fields = json.loads(fields)

        # Load original field mapping
        with open(field_mapping_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)

        original_fields = mapping.get('original_fields', [])

        # Create new DOCX template from original backup
        # by replacing placeholders while preserving formatting
        from docx import Document
        import re

        # Open original backup
        doc = Document(str(original_backup_path))
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

        # Create mapping: old_field -> new_field (for renamed placeholders)
        # And track: position -> new_field (for new placeholders)
        field_name_map = {}
        for i, new_name in enumerate(current_fields):
            if i < len(original_fields):
                field_name_map[original_fields[i]] = new_name

        # Update placeholders in DOCX (rename existing)
        for para in doc.paragraphs:
            _update_placeholders_in_element(para._p, current_fields, field_name_map, w_ns)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        _update_placeholders_in_element(para._p, current_fields, field_name_map, w_ns)

        # Check for new placeholders (added in HTML editor)
        new_fields = [f for f in current_fields if f not in original_fields]
        deleted_fields = [f for f in original_fields if f not in current_fields]

        # Handle new placeholders: Add them to the DOCX template
        if new_fields:
            # Add new placeholders at the end of document as separate section
            note_para = doc.add_paragraph()
            note_run = note_para.add_run(f"\n[New placeholders added: {', '.join(f'«{f}»' for f in new_fields)}]")
            note_run.font.size = Pt(8)
            note_run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)  # Gray

            # Insert new placeholders as merge fields at the end
            for field_name in new_fields:
                _insert_merge_field(doc, field_name)

            # Update original_fields to include new ones for future reference
            mapping['original_fields'] = current_fields

        # Handle deleted placeholders: Already removed from current_fields list
        # The rename logic above handles removal by not including deleted fields in the map

        # Save updated template
        doc.save(str(template_path))

        # Update field mapping
        mapping['fields'] = current_fields
        mapping['has_modifications'] = True

        with open(field_mapping_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

        return JSONResponse(content={
            "template_id": template_id,
            "fields": current_fields,
            "updated": True,
            "method": "docx_regenerated",
            "fields_added": len(current_fields) - len(original_fields),
            "original_field_count": len(original_fields)
        })

    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}\n{traceback.format_exc()}")


def _update_placeholders_in_element(element, current_fields, field_name_map, w_ns):
    """Update mail merge placeholders in an XML element

    Args:
        element: lxml element (paragraph or table cell)
        current_fields: List of current field names (in order)
        field_name_map: Mapping from old field names to new field names
        w_ns: Word namespace
    """
    import re

    # Process all fldSimple elements (mail merge fields)
    for fldSimple in element.findall(f".//{w_ns}fldSimple"):
        # Get field instruction
        instr = fldSimple.get(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", "")
        match = re.search(r'MERGEFIELD\s+(\S+)', instr)

        if match:
            old_field_name = match.group(1)
            # Map to new field name if renamed
            new_field_name = field_name_map.get(old_field_name, old_field_name)

            # Update instruction attribute
            new_instr = instr.replace(f'MERGEFIELD {old_field_name}', f'MERGEFIELD {new_field_name}')
            fldSimple.set(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}instr", new_instr)

            # Update text content in nested w:r/w:t
            for r in fldSimple.findall(f"{w_ns}r"):
                for t in r.findall(f"{w_ns}t"):
                    if t.text:
                        # Replace old placeholder with new placeholder
                        t.text = t.text.replace(f"«{old_field_name}»", f"«{new_field_name}»")


def _insert_merge_field(doc, field_name):
    """Insert a mail merge field at the end of document

    Args:
        doc: python-docx Document object
        field_name: Name of the field to insert
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    # Create new paragraph
    para = doc.add_paragraph()

    # Create fldSimple element (mail merge field)
    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    fldSimple = OxmlElement(f'{w_ns}fldSimple')
    fldSimple.set(f'{w_ns}instr', f'MERGEFIELD {field_name} \\* MERGEFORMAT')

    # Create run element
    r = OxmlElement(f'{w_ns}r')

    # Create run properties (optional formatting)
    rPr = OxmlElement(f'{w_ns}rPr')
    # Add simple formatting
    b = OxmlElement(f'{w_ns}b')  # Bold
    rPr.append(b)

    # Create text element with placeholder
    t = OxmlElement(f'{w_ns}t')
    t.set(qn('xml:space'), 'preserve')
    t.text = f'«{field_name}»'

    # Assemble
    r.append(rPr)
    r.append(t)
    fldSimple.append(r)

    # Add to paragraph
    para._p.append(fldSimple)


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
