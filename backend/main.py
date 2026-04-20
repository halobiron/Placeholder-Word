import os
import re
import uuid
from pathlib import Path
from typing import Dict, Literal
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import json
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from template_manager import MailMergeProcessor
from merge_executor import MergeExecutor
from gemini_client import GeminiClient
from docx_editor import DocxFullEditor
import traceback

# Setup paths
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATE_DIR = UPLOAD_DIR / "templates"
RESULT_DIR = UPLOAD_DIR / "results"
IMAGE_DIR = UPLOAD_DIR / "images"  # Directory for uploaded images

# Ensure directories exist
def ensure_directories():
    """Create required directories if they don't exist"""
    dirs_to_create = [UPLOAD_DIR, TEMPLATE_DIR, RESULT_DIR, IMAGE_DIR]
    for directory in dirs_to_create:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Create directory failed: {e}")

# Create directories on startup
ensure_directories()

# Load environment variables
load_dotenv()
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


@app.get("/")
async def root():
    """Root endpoint and Health check"""
    return {
        "status": "OK",
        "message": "Mail Merge Placeholder System API is running",
        "endpoints": {
            "root": "GET / (Health Check)",
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
    ensure_directories()
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

        processor = MailMergeProcessor(gemini_api_key=None)
        template_id = str(uuid.uuid4())
        output_path = TEMPLATE_DIR / f"{template_id}.docx"
        result = processor.convert_to_mail_merge(str(temp_path), str(output_path))

        # Build response
        response_data = {
            "template_id": result["template_id"],
            "fields": result["fields"],
            "field_count": result["field_count"],
            "html_preview": result["html_preview"],
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
            try:
                gemini_client = GeminiClient(GEMINI_API_KEY)
            except ValueError as e:
                raise HTTPException(status_code=500, detail=str(e))
            
            if active_fields:
                active_f = set(json.loads(active_fields))
                template_fields = [f for f in template_fields if f in active_f]

            print(f"=== MERGE DEBUG ===")
            print(f"Template fields to extract: {template_fields}")
            data = gemini_client.extract_data_from_context(
                context,
                template_fields
            )
            print(f"Extracted data: {data}")
            print(f"=== END MERGE DEBUG ===")
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
        html_preview = processor._generate_html_preview(str(result_path))

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
        print(f"[INFO] update_template called for '{template_id}' with map: {rename_mapping}")
        
        doc = Document(str(template_path))
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        flds = [f for f in doc.element.iter(f"{w_ns}fldSimple") if "MERGEFIELD" in f.get(f"{w_ns}instr", "")]

        count_updated = 0

        for fld in flds:
            instr = fld.get(f"{w_ns}instr", "")
            match = re.search(r'MERGEFIELD\s+(\S+)', instr)
            if match:
                current_name = match.group(1)
                new_name = rename_mapping.get(current_name)

                if new_name is None:
                    # DELETE: Replace field with original text from \z switch
                    z_match = re.search(r'\\z\s*"([^"]*)"', instr)
                    original_text = z_match.group(1) if z_match else f"«{current_name}»"

                    # Get parent element (paragraph or table cell)
                    parent = fld.getparent()

                    # Create a new run element with original text

                    new_run = OxmlElement('w:r')
                    new_t = OxmlElement('w:t')
                    new_t.set(qn('xml:space'), 'preserve')
                    new_t.text = original_text
                    new_run.append(new_t)

                    # Replace fldSimple with the run
                    parent.replace(fld, new_run)
                    count_updated += 1
                    print(f"[DELETE] Removed field '{current_name}', restored: '{original_text}'")

                elif new_name != current_name:
                    # RENAME: Keep the original \z part
                    z_match = re.search(r'\\z\s*"([^"]*)"', instr)
                    z_part = f' \\z "{z_match.group(1)}"' if z_match else ""

                    new_instr = f' MERGEFIELD {new_name} \\* MERGEFORMAT{z_part} '
                    fld.set(f"{w_ns}instr", new_instr)

                    for t in fld.iter(f"{w_ns}t"):
                        t.text = f"«{new_name}»"

                    count_updated += 1
            else:
                print(f"[WARNING] Could not parse MERGEFIELD from instr: {instr}")

        doc.save(str(template_path))
        print(f"[INFO] Successfully updated {count_updated} fields in '{template_id}'")

        return {
            "template_id": template_id, 
            "updated": True,
            "fields_updated": count_updated
        }
    except Exception as e:
        print(f"[ERROR] Update template failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

@app.post("/suggest-placeholders")
async def suggest_placeholders(template_id: str = Form(...)):
    """Analyze template with AI to detect missing placeholders

    Args:
        template_id: ID of template to analyze

    Returns:
        JSON with AI suggestions for missing placeholders
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        # Get existing fields from template
        executor = MergeExecutor()
        existing_fields = executor.get_template_fields(str(template_path))

        # Extract structured content for analysis
        processor = MailMergeProcessor()
        structured_content = processor.extract_structured_content(str(template_path))

        if not structured_content:
            raise HTTPException(
                status_code=500,
                detail="Failed to extract content from template"
            )

        # Analyze with Gemini
        gemini_client = GeminiClient(GEMINI_API_KEY)
        analysis = gemini_client.analyze_document_for_placeholders(
            structured_content,
            existing_fields
        )

        suggestions = analysis.get("suggestions", [])

        return {
            "template_id": template_id,
            "suggestions": suggestions
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )


@app.post("/apply-suggestions")
async def apply_ai_suggestions(
    template_id: str = Form(...),
    suggestions: str = Form(...)  # JSON string of suggestions to apply
):
    """Apply AI-generated placeholder suggestions to template

    Args:
        template_id: ID of template to update
        suggestions: JSON array of suggestions to apply

    Returns:
        JSON with update results
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        suggestions_list = json.loads(suggestions)

        if not suggestions_list:
            raise HTTPException(
                status_code=400,
                detail="No suggestions provided"
            )

        # Apply each suggestion
        processor = MailMergeProcessor(gemini_api_key=GEMINI_API_KEY)
        results = {
            "template_id": template_id,
            "total_suggestions": len(suggestions_list),
            "successful": 0,
            "failed": 0,
            "applied_fields": []
        }

        for suggestion in suggestions_list:
            block_index = suggestion.get("block_index")
            field_name = suggestion.get("suggested_name")
            context = suggestion.get("context", "")
            before_context = suggestion.get("before_context", [])
            after_context = suggestion.get("after_context", [])
            position = suggestion.get("position", "right")
            insert_after = suggestion.get("insert_after", None)

            if block_index is None or not field_name:
                results["failed"] += 1
                continue

            # Inject placeholder with full context and position
            success = processor.inject_placeholder_at_location(
                str(template_path),
                block_index,
                field_name,
                context,
                before_context,
                after_context,
                position,
                None,  # cell_index
                None,  # para_in_cell
                insert_after
            )

            if success:
                results["successful"] += 1
                results["applied_fields"].append(field_name)
            else:
                results["failed"] += 1

        # Get updated field list
        executor = MergeExecutor()
        updated_fields = executor.get_template_fields(str(template_path))

        results["updated_field_count"] = len(updated_fields)
        results["updated_fields"] = updated_fields

        return results

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply suggestions: {str(e)}"
        )


@app.post("/suggest-field-name")
async def suggest_field_name(
    template_id: str = Form(...),
    block_index: int = Form(...),
    para_in_cell: int = Form(None)
):
    """Suggest a field name based on the selected block's text

    Args:
        template_id: ID of template
        block_index: Index of content block to extract text from
        para_in_cell: Optional paragraph index within cell

    Returns:
        JSON with suggested field name
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        # Initialize processor
        processor = MailMergeProcessor(gemini_api_key=GEMINI_API_KEY)

        # Extract structured content
        structured_content = processor.extract_structured_content(str(template_path))

        # Extract text from block with fallback
        extracted_text = processor.extract_text_from_block_with_fallback(
            structured_content,
            block_index,
            para_in_cell
        )

        if not extracted_text:
            raise HTTPException(
                status_code=400,
                detail="Could not extract meaningful text from selected location"
            )

        # Generate smart field name
        field_name = processor.generate_smart_field_name(
            extracted_text,
            structured_content,
            block_index
        )

        return {
            "success": True,
            "field_name": field_name
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to suggest field name: {str(e)}"
        )


@app.post("/add-placeholder-by-position")
async def add_placeholder_by_position(
    template_id: str = Form(...),
    block_index: int = Form(...),
    field_name: str = Form(...),
    position: Literal["left", "right", "new_line"] = Form("right"),
    cell_index: int = Form(None),
    para_in_cell: int = Form(None)
):
    """Manually add a placeholder to a template at a specific location

    Args:
        template_id: ID of template to update
        block_index: Index of content block to inject placeholder into
        field_name: Name for the new placeholder (auto-generated if empty)
        position: Where to insert (left=before text, right=after text, new_line)
        cell_index: Optional cell index within a table (for table cells)
        para_in_cell: Optional paragraph index within a cell (for specific paragraph targeting)

    Returns:
        JSON with update results
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        # Initialize processor
        processor = MailMergeProcessor(gemini_api_key=GEMINI_API_KEY)

        # Clean and validate field name
        field_name = field_name.strip().lower().replace(" ", "_")
        if not field_name:
            raise HTTPException(
                status_code=400,
                detail="Field name cannot be empty"
            )

        # Inject placeholder (with cell_index and para_in_cell if provided)
        success = processor.inject_placeholder_at_location(
            str(template_path),
            block_index,
            field_name,
            "",  # No context hint needed for manual add
            [],  # No before_context needed
            [],  # No after_context needed
            position,
            cell_index,  # Pass cell_index for table cells
            para_in_cell  # Pass para_in_cell for specific paragraph targeting within cell
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to inject placeholder into document"
            )

        # Get updated field list and HTML preview
        executor = MergeExecutor()
        updated_fields = executor.get_template_fields(str(template_path))
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "field_name": field_name,
            "block_index": block_index,
            "cell_index": cell_index,
            "para_in_cell": para_in_cell,
            "position": position,
            "updated_fields": updated_fields,
            "field_count": len(updated_fields),
            "html_preview": html_preview
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add placeholder: {str(e)}"
        )


@app.post("/add-placeholder-by-offset")
async def add_placeholder_by_offset(
    template_id: str = Form(...),
    block_index: int = Form(...),
    offset: int = Form(...),
    field_name: str = Form(...),
    inherit_format: bool = Form(True),
    para_in_cell: int = Form(None)
):
    """Add placeholder at specific character offset within paragraph

    Args:
        template_id: ID of template to update
        block_index: Index of paragraph to insert placeholder into
        offset: Character offset within paragraph text
        field_name: Name for the new placeholder
        inherit_format: Whether to inherit format from surrounding text
        para_in_cell: Optional paragraph index within table cell (for table cell editing)

    Returns:
        JSON with update results
    """
    print(f"[INFO] add_placeholder_by_offset called: template_id={template_id}, block_index={block_index}, offset={offset}, field_name={field_name}, para_in_cell={para_in_cell}")

    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        print(f"[ERROR] Template not found: {template_path}")
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        # Clean field name
        field_name = field_name.strip().lower().replace(" ", "_")

        # Initialize editor
        from docx_editor import DocxFullEditor
        editor = DocxFullEditor(str(template_path))

        # Convert block_index to paragraph_index, handling table cells
        paragraph_index = block_index
        if para_in_cell is not None:
            print(f"[DEBUG] Converting table cell location: block_index={block_index}, para_in_cell={para_in_cell}")
            # Get actual paragraph_index for table cell paragraph
            paragraph_index = editor.get_table_cell_paragraph_index(block_index, para_in_cell)
            if paragraph_index is None:
                print(f"[ERROR] Failed to find paragraph in table cell: block_index={block_index}, para_in_cell={para_in_cell}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not find paragraph {para_in_cell} in table cell at block_index {block_index}"
                )
            print(f"[DEBUG] Converted to paragraph_index={paragraph_index}")

        # Insert placeholder at offset
        try:
            editor.insert_placeholder_at_offset(
                paragraph_index=paragraph_index,
                offset=offset,
                field_name=field_name,
                inherit_format=inherit_format
            )
        except ValueError as ve:
            # Validation errors (bad input)
            raise HTTPException(
                status_code=400,
                detail=f"Invalid input: {str(ve)}"
            )
        except RuntimeError as re:
            # Runtime errors (operation failed)
            raise HTTPException(
                status_code=500,
                detail=f"Insert operation failed: {str(re)}"
            )
        except Exception as e:
            # Unexpected errors
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected error during insertion: {type(e).__name__}: {str(e)}"
            )

        # Save document
        editor.save(str(template_path))

        # Get updated field list and HTML preview
        processor = MailMergeProcessor(gemini_api_key=GEMINI_API_KEY)
        executor = MergeExecutor()
        updated_fields = executor.get_template_fields(str(template_path))
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "field_name": field_name,
            "block_index": block_index,
            "offset": offset,
            "paragraph_index": paragraph_index,
            "para_in_cell": para_in_cell,
            "updated_fields": updated_fields,
            "field_count": len(updated_fields),
            "html_preview": html_preview
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Log unexpected errors with full context
        error_details = {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "template_id": template_id,
            "block_index": block_index,
            "offset": offset,
            "field_name": field_name,
            "traceback": traceback.format_exc()
        }
        print(f"[ERROR] Unexpected error in add_placeholder_by_offset: {error_details}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {type(e).__name__}: {str(e)}"
        )


@app.get("/template-info/{template_id}")
async def get_template_info(template_id: str):
    """Get current template information including fields

    Args:
        template_id: ID of template

    Returns:
        JSON with template fields and HTML preview
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        # Get fields from template
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        # Generate HTML preview
        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": html_preview
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get template info: {str(e)}"
        )


def map_camel_to_snake(format_data: dict) -> dict:
    """Map camelCase keys to snake_case for Python functions"""
    format_mapping = {
        'fontSize': 'font_size',
        'fontName': 'font_name',
        'allCaps': 'all_caps',
        'lineSpacing': 'line_spacing',
        'spaceBefore': 'space_before',
        'spaceAfter': 'space_after',
        'firstLineIndent': 'first_line_indent',
        'alignment': 'alignment'
    }
    return {format_mapping.get(k, k): v for k, v in format_data.items()}


@app.post("/edit-selection")
async def edit_selection(
    template_id: str = Form(...),
    edit_type: str = Form(...),
    selected_text: str = Form(...),
    new_text: str = Form(None),
    format_config: str = Form(None),
    paragraph_index: int = Form(None),
    run_index: int = Form(None),
    paragraph_format: str = Form(None)
):
    """Edit DOCX based on user selection from HTML preview"""
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        from docx_editor import DocxFullEditor

        editor = DocxFullEditor(str(template_path))

        # Debug logging
        print(f"=== /edit-selection DEBUG ===")
        print(f"template_id: {template_id}")
        print(f"edit_type: {edit_type}")
        print(f"selected_text: {selected_text[:50]}...")
        print(f"paragraph_index (block_index): {paragraph_index}")
        print(f"format_config: {format_config[:200] if format_config else None}...")
        print(f"=== END DEBUG ===")

        # Map block_index to paragraph_index if provided
        actual_para_index = None
        use_position = False

        if paragraph_index is not None:
            actual_para_index = editor.get_paragraph_index_from_block(paragraph_index)
            print(f"actual_para_index: {actual_para_index}")
            if actual_para_index is not None:
                use_position = True

        # Helper function for position-based text replacement
        def replace_text(old, new):
            if use_position:
                success = editor.replace_text_at_position(
                    old_text=old, new_text=new,
                    paragraph_index=actual_para_index, run_index=run_index
                )
                if not success:
                    raise HTTPException(status_code=404, detail="Text not found at specified position")
            else:
                editor.replace_text_keep_format(old_text=old, new_text=new)

        # Helper function for position-based formatting
        def apply_format(text, format_data):
            try:
                format_kwargs = map_camel_to_snake(format_data)
                print(f"apply_format kwargs: {format_kwargs}")
            except Exception as e:
                print(f"Error mapping format data: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid format data: {str(e)}")

            if use_position:
                success = editor.apply_format_at_position(
                    text=text, paragraph_index=actual_para_index, **format_kwargs
                )
                if not success:
                    raise HTTPException(status_code=404, detail="Text not found at specified position")
            else:
                editor.apply_format_to_text(text=text, **format_kwargs)

        # Process edit type
        if edit_type == "text":
            if not new_text:
                raise HTTPException(status_code=400, detail="new_text required")
            replace_text(selected_text, new_text)

        elif edit_type == "format":
            if not format_config:
                raise HTTPException(status_code=400, detail="format_config required")
            try:
                format_data = json.loads(format_config)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON in format_config: {str(e)}")
            apply_format(selected_text, format_data)

        elif edit_type == "both":
            if not new_text:
                raise HTTPException(status_code=400, detail="new_text required")
            if not format_config:
                raise HTTPException(status_code=400, detail="format_config required")

            try:
                format_data = json.loads(format_config)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON in format_config: {str(e)}")

            replace_text(selected_text, new_text)
            apply_format(new_text, format_data)

        elif edit_type == "delete":
            replace_text(selected_text, "")

        else:
            raise HTTPException(status_code=400, detail=f"Invalid edit_type: {edit_type}")

        # Handle paragraph formatting if provided
        if paragraph_format:
            try:
                paragraph_format_data = json.loads(paragraph_format)
                paragraph_kwargs = map_camel_to_snake(paragraph_format_data)
                print(f"paragraph_format kwargs: {paragraph_kwargs}")

                if actual_para_index is not None:
                    success = editor.apply_paragraph_formatting(
                        paragraph_index=actual_para_index,
                        **paragraph_kwargs
                    )
                    if not success:
                        print(f"Warning: Could not apply paragraph formatting at index {actual_para_index}")
                else:
                    print(f"Warning: Paragraph formatting requested but no paragraph_index provided")
            except Exception as e:
                print(f"Error applying paragraph format: {e}")
                print(f"Traceback: {traceback.format_exc()}")

        # Save and return updated preview
        editor.save(str(template_path))

        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))
        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "fields": fields,
            "html_preview": html_preview,
            "updated": True,
            "edit_type": edit_type
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Edit failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /edit-selection ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/add-content")
async def add_content(
    template_id: str = Form(...),
    add_type: str = Form(...),  # "text", "paragraph", "placeholder", "image", "pagebreak"
    position: str = Form(...),   # "end", "after:text", "before:text"
    content: str = Form(None),   # Text content
    field_name: str = Form(None), # Field name for placeholder
    file: UploadFile = None,     # Image file
    inherit_format: bool = Form(True),  # Inherit format from nearby text
    format_config: str = Form(None)  # Format options for new content
):
    """
    Add new content to template

    Args:
        template_id: Template ID
        add_type: Type of content to add
        position: Where to add ("end", "after:text", "before:text")
        content: Text/paragraph content
        field_name: Field name for placeholder
        file: Image file (for image type)
        inherit_format: True = inherit format from nearby text
        format_config: Format options (optional)

    Returns:
        Updated template and preview
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        from docx_editor import DocxFullEditor
        import tempfile

        editor = DocxFullEditor(str(template_path))

        if add_type == "text":
            # Add text
            if not content:
                raise HTTPException(status_code=400, detail="content required for text addition")

            # Helper function to find paragraph index by text or element
            def find_paragraph_index(target_text=None, target_element=None):
                for idx, para in enumerate(editor._iterate_paragraphs_in_doc_order()):
                    if target_text is not None and target_text in para.text:
                        return idx
                    if target_element is not None and para._element == target_element:
                        return idx
                return None

            content_paragraph_index = None

            if position == "end":
                # Add text at end
                last_para = editor.doc.paragraphs[-1]
                last_para.add_run(content)
                content_paragraph_index = find_paragraph_index(target_element=last_para._element)
            elif position.startswith("after:"):
                target_text = position.split("after:")[1].strip()
                content_paragraph_index = find_paragraph_index(target_text=target_text)
                success = editor.add_text_after(target_text, content, inherit_format=inherit_format)
                if not success:
                    raise HTTPException(status_code=404, detail=f"Target text not found: {target_text}")
            elif position.startswith("before:"):
                target_text = position.split("before:")[1].strip()
                content_paragraph_index = find_paragraph_index(target_text=target_text)
                success = editor.add_text_before(target_text, content, inherit_format=inherit_format)
                if not success:
                    raise HTTPException(status_code=404, detail=f"Target text not found: {target_text}")

            # Apply format if provided
            if format_config:
                format_data = json.loads(format_config)
                # Pass paragraph_index to only format the newly added content
                editor.apply_format_to_text(content, paragraph_index=content_paragraph_index, **map_camel_to_snake(format_data))

        elif add_type == "paragraph":
            # Add paragraph
            if not content:
                raise HTTPException(status_code=400, detail="content required for paragraph addition")

            if position == "end":
                editor.add_paragraph_at_end(content)
            elif position.startswith("after:"):
                target_text = position.split("after:")[1].strip()
                success = editor.add_paragraph_after(target_text, content, inherit_format=inherit_format)
                if not success:
                    raise HTTPException(status_code=404, detail=f"Target text not found: {target_text}")

            # Apply paragraph format if provided
            if format_config:
                format_data = json.loads(format_config)
                # Apply paragraph-level formatting
                if "alignment" in format_data:
                    editor.apply_paragraph_format(content, alignment=format_data["alignment"])

        elif add_type == "placeholder":
            # Add placeholder
            if not field_name:
                raise HTTPException(status_code=400, detail="field_name required for placeholder addition")

            editor.add_placeholder(field_name, position)

        elif add_type == "image":
            # Add image
            if not file:
                raise HTTPException(status_code=400, detail="file required for image addition")

            # Save uploaded image temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(await file.read())
                tmp_path = tmp.name

            try:
                # Extract width from format_config if provided
                width = 4.0  # Default width
                if format_config:
                    format_data = json.loads(format_config)
                    width = format_data.get("width", 4.0)

                success = editor.add_image(tmp_path, position, width=width)
                if not success and position != "end":
                    raise HTTPException(status_code=404, detail="Target text not found for image placement")
            finally:
                # Cleanup temp file
                import os
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        elif add_type == "pagebreak":
            # Add page break
            editor.add_page_break(position)

        else:
            raise HTTPException(status_code=400, detail=f"Invalid add_type: {add_type}")

        # Save updated template
        editor.save(str(template_path))

        # Get updated fields and preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "fields": fields,
            "html_preview": html_preview,
            "added": True,
            "add_type": add_type
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Add content failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)

@app.post("/add-hyperlink")
async def add_hyperlink_to_template(
    template_id: str = Form(...),
    block_index: int = Form(...),
    start_offset: int = Form(...),
    end_offset: int = Form(...),
    url: str = Form(...)
):
    """
    Add hyperlink to selected text range

    Args:
        template_id: Template ID
        block_index: Block index from HTML preview
        start_offset: Start character offset of selected text
        end_offset: End character offset of selected text
        url: Target URL

    Returns:
        Updated template and preview
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        from docx_editor import DocxFullEditor

        editor = DocxFullEditor(str(template_path))

        # Map block_index to paragraph_index
        paragraph_index = editor.get_paragraph_index_from_block(block_index)
        if paragraph_index is None:
            raise HTTPException(status_code=400, detail=f"Invalid block_index: {block_index}")

        print(f"[DEBUG] Mapped block_index={block_index} to paragraph_index={paragraph_index}")
        print(f"[DEBUG] Adding hyperlink to range [{start_offset}, {end_offset}] -> {url}")

        success = editor.add_hyperlink(paragraph_index, start_offset, end_offset, url)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to add hyperlink")

        # Save updated template
        editor.save(str(template_path))

        # Get updated fields and preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "fields": fields,
            "html_preview": html_preview,
            "added": True,
            "hyperlink": {"start_offset": start_offset, "end_offset": end_offset, "url": url}
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Add hyperlink failed: {str(e)}")

@app.post("/update-text")
async def update_text_in_template(
    template_id: str = Form(...),
    block_index: int = Form(...),
    old_text: str = Form(""),  # Changed to allow empty string for new cells
    new_text: str = Form(""),
    edit_type: str = Form("text"),
    para_in_cell: int = Form(None)  # NEW: Support table cell paragraph editing
):
    """Update text in template while preserving formatting

    Optimized for direct text editing on HTML preview with contenteditable.

    Args:
        template_id: Template identifier
        block_index: Block index in HTML preview
        old_text: Original text (for fuzzy matching)
        new_text: New text to replace with (empty string for deletion)
        edit_type: Type of edit (text-only in this case)
        para_in_cell: Optional paragraph index within table cell for precise targeting

    Returns:
        Updated template with new HTML preview
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"

    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        from docx_editor import DocxFullEditor

        print(f"=== /update-text DEBUG ===")
        print(f"block_index: {block_index}")
        print(f"para_in_cell: {para_in_cell}")
        print(f"old_text: '{old_text[:50]}...'")
        print(f"new_text: '{new_text[:50]}...'")
        print(f"=== END DEBUG ===")

        editor = DocxFullEditor(str(template_path))

        # Convert block_index to paragraph_index, handling table cells
        para_index = block_index
        if para_in_cell is not None:
            print(f"[DEBUG] Converting table cell location: block_index={block_index}, para_in_cell={para_in_cell}")
            # Get actual paragraph_index for table cell paragraph
            para_index = editor.get_table_cell_paragraph_index(block_index, para_in_cell)
            if para_index is None:
                print(f"[ERROR] Failed to find paragraph in table cell: block_index={block_index}, para_in_cell={para_in_cell}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not find paragraph {para_in_cell} in table cell at block_index {block_index}"
                )
            print(f"[DEBUG] Converted to para_index={para_index}")
        else:
            # Original logic for non-table-cell paragraphs
            para_index = editor.get_paragraph_index_from_block(block_index)
            if para_index is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid block_index: {block_index}"
                )

        # Handle deletion (empty new_text) or replacement
        if new_text == "":
            # Deletion: replace old text with empty string
            success = editor.replace_text_at_position(
                old_text=old_text,
                new_text="",
                paragraph_index=para_index
            )
        else:
            # CRITICAL FIX: Check if old_text is empty or cell is empty
            # If old_text is empty or cell is empty, ADD text instead of REPLACE
            if not old_text or old_text.strip() == "":
                # Adding text to empty cell - get target paragraph first
                target_paragraph = None
                for idx, para in enumerate(editor._iterate_paragraphs_in_doc_order()):
                    if idx == para_index:
                        target_paragraph = para
                        break

                if target_paragraph and not target_paragraph.text.strip():
                    # Empty paragraph - add text directly
                    # CRITICAL: Copy alignment from first paragraph in same cell for table cells
                    # This preserves center/right alignment when adding text to empty paragraphs
                    if para_in_cell is not None and block_index is not None:
                        # Get all paragraphs in this cell
                        cell_paragraphs = editor.get_table_cell_paragraphs(block_index)
                        if cell_paragraphs and len(cell_paragraphs) > 0:
                            # Copy alignment from first paragraph in cell
                            first_para = cell_paragraphs[0]
                            if first_para.alignment is not None:
                                target_paragraph.alignment = first_para.alignment
                                print(f"[DEBUG] Copied alignment from first paragraph: {first_para.alignment}")

                    # Check if paragraph has runs
                    if target_paragraph.runs:
                        # Add to existing run
                        target_paragraph.runs[0].text = new_text
                    else:
                        # Create new run with text using docx API
                        new_run = target_paragraph.add_run(new_text)

                    success = True
                    print(f"[DEBUG] Added text '{new_text}' to empty paragraph at index {para_index}")
                else:
                    # Paragraph has content or couldn't find - try normal replace
                    print(f"[DEBUG] Paragraph has content or not found, trying normal replace")
                    success = editor.replace_text_at_position(
                        old_text=old_text if old_text else "",
                        new_text=new_text,
                        paragraph_index=para_index
                    )
            else:
                # Normal replacement: replace with new text
                success = editor.replace_text_at_position(
                    old_text=old_text,
                    new_text=new_text,
                    paragraph_index=para_index
                )

        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to replace text: '{old_text[:50]}...' not found at block {block_index}"
            )

        print(f"[DEBUG] Text update successful, saving document...")

        # Save updated template
        editor.save(str(template_path))

        print(f"[DEBUG] Document saved, regenerating HTML preview...")

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        print(f"[DEBUG] HTML preview regenerated, length: {len(html_preview)}")

        return {
            "template_id": template_id,
            "updated": True,
            "fields": fields,
            "html_preview": html_preview,
            "edit_type": "text",
            "block_index": block_index,
            "action": "delete" if new_text == "" else "update"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Text update failed: {str(e)}\n{traceback.format_exc()}"
        )


@app.post("/get-selection-format")
async def get_selection_format(
    template_id: str = Form(...),
    selected_text: str = Form(...),
    block_index: int = Form(None)
):
    """
    Extract accurate formatting information for selected text from DOCX

    Args:
        template_id: Template ID
        selected_text: Text to extract format from
        block_index: Block index in HTML preview (for precision, optional)

    Returns:
        JSON with accurate format info from DOCX:
        {
            'bold': bool,
            'italic': bool,
            'underline': str (none/single/double),
            'strikethrough': bool,
            'color': str (hex, e.g., 'FF0000'),
            'highlight': str (hex or null),
            'fontSize': int (points),
            'fontName': str
        }
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        from docx_editor import DocxFullEditor

        editor = DocxFullEditor(str(template_path))

        # Map block_index to paragraph_index if provided
        actual_para_index = None
        if block_index is not None:
            actual_para_index = editor.get_paragraph_index_from_block(block_index)

        # Extract format from DOCX
        format_info = editor.get_format_at_position(
            text=selected_text,
            paragraph_index=actual_para_index
        )

        if not format_info:
            # Return default format if not found
            format_info = {
                'bold': False,
                'italic': False,
                'underline': 'none',
                'strikethrough': False,
                'subscript': False,
                'superscript': False,
                'color': '000000',
                'highlight': None,
                'fontSize': 12,
                'fontName': 'Times New Roman'
            }

        # Convert to frontend format
        frontend_format = {
            'bold': format_info.get('bold', False),
            'italic': format_info.get('italic', False),
            'underline': format_info.get('underline', 'none') != 'none',
            'strikethrough': format_info.get('strikethrough', False),
            'subscript': format_info.get('subscript', False),
            'superscript': format_info.get('superscript', False),
            'color': '#' + format_info.get('color', '000000'),
            'fontSize': format_info.get('font_size', 12),
            'fontName': format_info.get('font_name', 'Times New Roman')
        }

        # Include highlight color if present
        if format_info.get('highlight'):
            frontend_format['highlight'] = '#' + format_info['highlight']

        return {
            'template_id': template_id,
            'selected_text': selected_text,
            'format': frontend_format
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Format extraction failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /get-selection-format ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


# ===== TABLE OPERATION ENDPOINTS =====

@app.post("/add-table-row")
async def add_table_row(request: Request):
    """Thêm row mới vào bảng"""
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        table_index = form.get("table_index")
        row_index = form.get("row_index")  # Optional: insert at specific position
        position = form.get("position", "below")  # "above" or "below"

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if not table_index:
            raise HTTPException(status_code=400, detail="table_index is required")

        # Convert to integers
        try:
            table_index = int(table_index)
            row_index = int(row_index) if row_index else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid table_index or row_index")

        # Validate position
        if position not in ["above", "below"]:
            raise HTTPException(status_code=400, detail="position must be 'above' or 'below'")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Calculate insertion index based on position
        insert_index = row_index if row_index is not None else len(editor.doc.tables[table_index].rows)

        if position == "below" and insert_index is not None:
            insert_index = insert_index + 1

        # Insert row
        success = editor.insert_table_row(table_index, insert_index)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to add table row")

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "html_preview": html_preview,
            "operation": "add_row",
            "table_index": table_index,
            "position": position
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Add table row failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /add-table-row ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/delete-table-row")
async def delete_table_row(request: Request):
    """Xóa row khỏi bảng"""
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        table_index = form.get("table_index")
        row_index = form.get("row_index")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if not table_index:
            raise HTTPException(status_code=400, detail="table_index is required")
        if not row_index:
            raise HTTPException(status_code=400, detail="row_index is required")

        # Convert to integers
        try:
            table_index = int(table_index)
            row_index = int(row_index)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid table_index or row_index")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Delete row
        success = editor.delete_table_row(table_index, row_index)

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to delete table row. Check if row index is valid or if it's the last row."
            )

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "html_preview": html_preview,
            "operation": "delete_row",
            "table_index": table_index,
            "row_index": row_index
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Delete table row failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /delete-table-row ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/add-table-column")
async def add_table_column(request: Request):
    """Thêm column mới vào bảng"""
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        table_index = form.get("table_index")
        col_index = form.get("col_index")  # Optional: insert at specific position
        position = form.get("position", "right")  # "left" or "right"

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if not table_index:
            raise HTTPException(status_code=400, detail="table_index is required")

        # Convert to integers
        try:
            table_index = int(table_index)
            col_index = int(col_index) if col_index else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid table_index or col_index")

        # Validate position
        if position not in ["left", "right"]:
            raise HTTPException(status_code=400, detail="position must be 'left' or 'right'")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Calculate insertion index based on position
        insert_index = col_index if col_index is not None else len(editor.doc.tables[table_index].rows[0].cells)

        if position == "right" and insert_index is not None:
            insert_index = insert_index + 1

        # Insert column
        success = editor.insert_table_column(table_index, insert_index)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to add table column")

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "html_preview": html_preview,
            "operation": "add_column",
            "table_index": table_index,
            "position": position
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Add table column failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /add-table-column ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/delete-table-column")
async def delete_table_column(request: Request):
    """Xóa column khỏi bảng"""
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        table_index = form.get("table_index")
        col_index = form.get("col_index")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if not table_index:
            raise HTTPException(status_code=400, detail="table_index is required")
        if not col_index:
            raise HTTPException(status_code=400, detail="col_index is required")

        # Convert to integers
        try:
            table_index = int(table_index)
            col_index = int(col_index)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid table_index or col_index")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Delete column
        success = editor.delete_table_column(table_index, col_index)

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to delete table column. Check if column index is valid or if it's the last column."
            )

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "html_preview": html_preview,
            "operation": "delete_column",
            "table_index": table_index,
            "col_index": col_index
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Delete table column failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /delete-table-column ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/format-table-cell")
async def format_table_cell(request: Request):
    """Format table cell (background color, vertical/horizontal alignment, borders)

    Supports 9 alignment options (3 horizontal × 3 vertical):
    - Horizontal: left, center, right
    - Vertical: top, center, bottom

    Example format_options:
    {
        "horizontal_align": "center",
        "vertical_align": "middle",
        "background_color": "#FFFF00"
    }
    """
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        table_index = form.get("table_index")
        row_index = form.get("row_index")
        col_index = form.get("col_index")
        format_options_str = form.get("format_options")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if not table_index:
            raise HTTPException(status_code=400, detail="table_index is required")
        if not row_index:
            raise HTTPException(status_code=400, detail="row_index is required")
        if not col_index:
            raise HTTPException(status_code=400, detail="col_index is required")
        if not format_options_str:
            raise HTTPException(status_code=400, detail="format_options is required")

        # Convert to integers
        try:
            table_index = int(table_index)
            row_index = int(row_index)
            col_index = int(col_index)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid table_index, row_index, or col_index")

        # Parse format options JSON
        try:
            format_options = json.loads(format_options_str)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid format_options JSON: {str(e)}")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Format cell
        success = editor.format_table_cell(table_index, row_index, col_index, format_options)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to format table cell")

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "html_preview": html_preview,
            "operation": "format_cell",
            "table_index": table_index,
            "row_index": row_index,
            "col_index": col_index,
            "format_options": format_options
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Format table cell failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /format-table-cell ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/add-paragraph")
async def add_paragraph(request: Request):
    """Thêm paragraph mới vào template

    Args:
        template_id: Template ID
        block_index: Block index của paragraph phía trên (sẽ thêm paragraph mới sau đó)
        position: "after" (thêm sau block), "end" (thêm cuối document)
        text: Nội dung text cho paragraph mới (optional)
        table_index: Index của table (nếu thêm paragraph trong table cell)
        row_index: Row index của table cell
        col_index: Column index của table cell
        para_in_cell: Paragraph index trong cell (nếu thêm sau một paragraph cụ thể trong cell)

    Returns:
        Updated template với new paragraph và HTML preview
    """
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        block_index = form.get("block_index")
        position = form.get("position", "after")
        text = form.get("text", "")
        table_index = form.get("table_index")
        row_index = form.get("row_index")
        col_index = form.get("col_index")
        para_in_cell = form.get("para_in_cell")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")

        # Convert parameters to appropriate types
        try:
            if block_index:
                block_index = int(block_index)
            if table_index:
                table_index = int(table_index)
            if row_index:
                row_index = int(row_index)
            if col_index:
                col_index = int(col_index)
            if para_in_cell:
                para_in_cell = int(para_in_cell)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid numeric parameters")

        # Validate position
        if position not in ["after", "end"]:
            raise HTTPException(status_code=400, detail="position must be 'after' or 'end'")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        success = False

        # Case 1: Add paragraph within a table cell
        if table_index is not None and row_index is not None and col_index is not None:
            # Add paragraph in table cell
            success = editor.add_paragraph_in_table_cell(
                table_index, row_index, col_index,
                text, para_in_cell
            )
        # Case 2: Add paragraph after a specific block
        elif block_index is not None and position == "after":
            # Get paragraph index from block index
            para_index = editor.get_paragraph_index_from_block(block_index)

            if para_index is not None:
                # Find target paragraph
                target_paragraph = None
                for idx, para in enumerate(editor._iterate_paragraphs_in_doc_order()):
                    if idx == para_index:
                        target_paragraph = para
                        break

                if target_paragraph:
                    # Insert new paragraph after target
                    editor.insert_paragraph_after(target_paragraph, text)
                    success = True
            else:
                raise HTTPException(status_code=400, detail=f"Invalid block_index: {block_index}")
        # Case 3: Add paragraph at end of document
        elif position == "end":
            editor.add_paragraph_at_end(text)
            success = True

        if not success:
            raise HTTPException(status_code=400, detail="Failed to add paragraph")

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": html_preview,
            "operation": "add_paragraph",
            "block_index": block_index,
            "position": position,
            "text": text
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Add paragraph failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /add-paragraph ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/delete-paragraph")
async def delete_paragraph(request: Request):
    """Xóa paragraph khỏi template

    Args:
        template_id: Template ID
        block_index: Block index của paragraph cần xóa
        table_index: Index của table (nếu xóa paragraph trong table cell)
        row_index: Row index của table cell
        col_index: Column index của table cell
        para_in_cell: Paragraph index trong cell (nếu xóa paragraph cụ thể trong cell)

    Returns:
        Updated template sau khi xóa và HTML preview
    """
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        block_index = form.get("block_index")
        table_index = form.get("table_index")
        row_index = form.get("row_index")
        col_index = form.get("col_index")
        para_in_cell = form.get("para_in_cell")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if block_index is None:
            raise HTTPException(status_code=400, detail="block_index is required")

        # Convert parameters to appropriate types
        try:
            block_index = int(block_index)
            if table_index:
                table_index = int(table_index)
            if row_index:
                row_index = int(row_index)
            if col_index:
                col_index = int(col_index)
            if para_in_cell:
                para_in_cell = int(para_in_cell)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid numeric parameters")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        success = False

        # Case 1: Delete paragraph within a table cell
        if table_index is not None and row_index is not None and col_index is not None:
            # Get the cell
            if table_index < len(editor.doc.tables):
                table = editor.doc.tables[table_index]
                if row_index < len(table.rows):
                    row = table.rows[row_index]
                    if col_index < len(row.cells):
                        cell = row.cells[col_index]

                        # Delete paragraph at index
                        if para_in_cell is not None and para_in_cell < len(cell.paragraphs):
                            para_to_delete = cell.paragraphs[para_in_cell]
                            success = editor.delete_paragraph(para_to_delete)
        # Case 2: Delete regular paragraph
        else:
            # Get paragraph index from block index
            para_index = editor.get_paragraph_index_from_block(block_index)

            if para_index is not None:
                # Find target paragraph
                target_paragraph = None
                for idx, para in enumerate(editor._iterate_paragraphs_in_doc_order()):
                    if idx == para_index:
                        target_paragraph = para
                        break

                if target_paragraph:
                    # Delete the paragraph
                    success = editor.delete_paragraph(target_paragraph)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to delete paragraph")

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": html_preview,
            "operation": "delete_paragraph",
            "block_index": block_index
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Delete paragraph failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /delete-paragraph ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/delete-multiple-paragraphs")
async def delete_multiple_paragraphs(request: Request):
    """Xóa nhiều paragraphs cùng lúc khỏi template

    Args:
        template_id: Template ID
        blocks: JSON string của danh sách blocks cần xóa
              Format: [{"block_index": int, "table_index": int|None, "row_index": int|None,
                       "col_index": int|None, "para_in_cell": int|None}]

    Returns:
        Updated template sau khi xóa và HTML preview
    """
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        blocks_str = form.get("blocks")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if not blocks_str:
            raise HTTPException(status_code=400, detail="blocks is required")

        # Parse blocks JSON
        try:
            blocks = json.loads(blocks_str)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid blocks JSON: {str(e)}")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Sort blocks by index in descending order to avoid index shifting issues
        # When deleting, we should delete from highest index to lowest index
        blocks_with_indices = []

        for block_data in blocks:
            block_index = block_data.get("block_index")
            table_index = block_data.get("table_index")
            row_index = block_data.get("row_index")
            col_index = block_data.get("col_index")
            para_in_cell = block_data.get("para_in_cell")

            # Convert to int
            try:
                block_index = int(block_index) if block_index is not None else None
                table_index = int(table_index) if table_index is not None else None
                row_index = int(row_index) if row_index is not None else None
                col_index = int(col_index) if col_index is not None else None
                para_in_cell = int(para_in_cell) if para_in_cell is not None else None
            except ValueError:
                continue  # Skip invalid blocks

            # Determine the document paragraph index for each block
            if table_index is not None and row_index is not None and col_index is not None:
                # Table cell paragraph - use para_in_cell directly
                sort_key = (1000000, table_index, row_index, col_index, para_in_cell or 0)
                blocks_with_indices.append({
                    "sort_key": sort_key,
                    "block_index": block_index,
                    "table_index": table_index,
                    "row_index": row_index,
                    "col_index": col_index,
                    "para_in_cell": para_in_cell,
                    "is_table": True
                })
            else:
                # Regular paragraph - get paragraph index from block index
                para_index = editor.get_paragraph_index_from_block(block_index)
                if para_index is not None:
                    sort_key = (0, para_index)
                    blocks_with_indices.append({
                        "sort_key": sort_key,
                        "block_index": block_index,
                        "para_index": para_index,
                        "is_table": False
                    })

        # Sort by sort_key in descending order (delete from highest index first)
        blocks_with_indices.sort(key=lambda x: x["sort_key"], reverse=True)

        # Delete paragraphs in descending order
        deleted_count = 0
        for block_data in blocks_with_indices:
            try:
                if block_data["is_table"]:
                    # Delete table cell paragraph
                    table_index = block_data["table_index"]
                    row_index = block_data["row_index"]
                    col_index = block_data["col_index"]
                    para_in_cell = block_data["para_in_cell"]

                    if (table_index < len(editor.doc.tables) and
                        row_index < len(editor.doc.tables[table_index].rows) and
                        col_index < len(editor.doc.tables[table_index].rows[row_index].cells)):

                        cell = editor.doc.tables[table_index].rows[row_index].cells[col_index]

                        if para_in_cell is not None and para_in_cell < len(cell.paragraphs):
                            para_to_delete = cell.paragraphs[para_in_cell]
                            success = editor.delete_paragraph(para_to_delete)
                            if success:
                                deleted_count += 1
                else:
                    # Delete regular paragraph
                    para_index = block_data["para_index"]

                    # Find the paragraph at this index
                    target_paragraph = None
                    for idx, para in enumerate(editor._iterate_paragraphs_in_doc_order()):
                        if idx == para_index:
                            target_paragraph = para
                            break

                    if target_paragraph:
                        success = editor.delete_paragraph(target_paragraph)
                        if success:
                            deleted_count += 1
            except Exception as e:
                print(f"Error deleting block {block_data}: {e}")
                continue  # Continue with other blocks even if one fails

        # Save updated template
        editor.save(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": html_preview,
            "operation": "delete_multiple_paragraphs",
            "deleted_count": deleted_count
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Delete multiple paragraphs failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /delete-multiple-paragraphs ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/add-table-at-cursor")
async def add_table_at_cursor(request: Request):
    """Thêm bảng mới tại vị trí cursor chính xác

    Args:
        template_id: Template ID
        block_index: Block index từ HTML preview (chỉ định paragraph)
        offset: Character offset trong paragraph (vị trí cursor)
        rows: Số hàng cho bảng mới (default: 3)
        cols: Số cột cho bảng mới (default: 3)

    Returns:
        Updated template với bảng mới và HTML preview
    """
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        block_index = form.get("block_index")
        offset = form.get("offset")
        rows = form.get("rows", "3")
        cols = form.get("cols", "3")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if block_index is None:
            raise HTTPException(status_code=400, detail="block_index is required")
        if offset is None:
            raise HTTPException(status_code=400, detail="offset is required")

        # Parse numeric parameters
        try:
            block_index = int(block_index)
            offset = int(offset)
            rows = int(rows)
            cols = int(cols)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid numeric parameters")

        # Validate ranges
        if rows < 1 or rows > 20:
            raise HTTPException(status_code=400, detail="rows must be between 1 and 20")
        if cols < 1 or cols > 10:
            raise HTTPException(status_code=400, detail="cols must be between 1 and 10")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be >= 0")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        print(f"[INFO] add_table_at_cursor called: template_id={template_id}, block_index={block_index}, offset={offset}, rows={rows}, cols={cols}")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Log initial document state
        print(f"[DEBUG] Initial document has {len(editor.doc.tables)} tables")

        # Map block_index to paragraph_index
        paragraph_index = editor.get_paragraph_index_from_block(block_index)
        if paragraph_index is None:
            raise HTTPException(status_code=400, detail=f"Invalid block_index: {block_index}")

        print(f"[DEBUG] Mapped block_index={block_index} to paragraph_index={paragraph_index}")

        # Add table at cursor position
        try:
            editor.add_table_at_cursor(
                paragraph_index=paragraph_index,
                offset=offset,
                rows=rows,
                cols=cols
            )
            print(f"[INFO] Successfully added table at cursor position")
            print(f"[DEBUG] Document now has {len(editor.doc.tables)} tables after add_table_at_cursor")
        except Exception as e:
            error_detail = f"Failed to add table at cursor: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            print(f"=== add_table_at_cursor ERROR ===")
            print(error_detail)
            print(f"=== END ERROR ===")
            raise HTTPException(status_code=500, detail=error_detail)

        # Save updated template
        editor.save(str(template_path))
        print(f"[DEBUG] Document saved to {template_path}")

        # IMPORTANT: Reload editor from saved file to get latest document structure
        # This ensures the new table is included in HTML preview
        editor = DocxFullEditor(str(template_path))
        print(f"[DEBUG] Reloaded document has {len(editor.doc.tables)} tables")

        # Regenerate HTML preview with reloaded editor
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))
        print(f"[DEBUG] HTML preview regenerated, length: {len(html_preview)}")

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": html_preview,
            "operation": "add_table_at_cursor",
            "table_size": f"{rows}x{cols}"
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Add table at cursor failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /add-table-at-cursor ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/add-image-at-cursor")
async def add_image_at_cursor(request: Request):
    """Thêm ảnh tại vị trí cursor chính xác

    Args:
        template_id: Template ID
        block_index: Block index từ HTML preview
        offset: Character offset trong paragraph
        image: Upload image file
        width: Image width in inches (default: 4.0)

    Returns:
        Updated template với ảnh mới và HTML preview
    """
    try:
        # Parse form data
        form = await request.form()
        template_id = form.get("template_id")
        block_index = form.get("block_index")
        offset = form.get("offset")
        width = form.get("width", "4.0")

        # Get uploaded file
        image_file = form.get("image")
        if not image_file:
            raise HTTPException(status_code=400, detail="image file is required")

        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
        if block_index is None:
            raise HTTPException(status_code=400, detail="block_index is required")
        if offset is None:
            raise HTTPException(status_code=400, detail="offset is required")

        # Parse numeric parameters
        try:
            block_index = int(block_index)
            offset = int(offset)
            width = float(width)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid numeric parameters")

        # Validate ranges
        if width < 1.0 or width > 8.0:
            raise HTTPException(status_code=400, detail="width must be between 1.0 and 8.0 inches")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be >= 0")

        # Check template exists
        template_path = TEMPLATE_DIR / f"{template_id}.docx"
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Template not found")

        print(f"[INFO] add_image_at_cursor called: template_id={template_id}, block_index={block_index}, offset={offset}, width={width}")

        # Validate image file
        if not image_file.filename:
            raise HTTPException(status_code=400, detail="Invalid image file")

        # Check file extension
        allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
        file_ext = Path(image_file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            )

        # Generate unique filename
        import uuid
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        image_path = IMAGE_DIR / unique_filename

        # Save uploaded image
        try:
            with open(image_path, "wb") as buffer:
                content = await image_file.read()
                buffer.write(content)
            print(f"[DEBUG] Image saved to: {image_path}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Map block_index to paragraph_index
        paragraph_index = editor.get_paragraph_index_from_block(block_index)
        if paragraph_index is None:
            raise HTTPException(status_code=400, detail=f"Invalid block_index: {block_index}")

        print(f"[DEBUG] Mapped block_index={block_index} to paragraph_index={paragraph_index}")

        # Add image at cursor position
        try:
            editor.add_image_at_cursor(
                paragraph_index=paragraph_index,
                offset=offset,
                image_path=str(image_path),
                width=width
            )
            print(f"[INFO] Successfully added image at cursor position")
        except Exception as e:
            error_detail = f"Failed to add image at cursor: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            print(f"=== add_image_at_cursor ERROR ===")
            print(error_detail)
            print(f"=== END ERROR ===")
            raise HTTPException(status_code=500, detail=error_detail)

        # Save updated template
        editor.save(str(template_path))

        # IMPORTANT: Reload editor from saved file
        editor = DocxFullEditor(str(template_path))

        # Regenerate HTML preview
        executor = MergeExecutor()
        fields = executor.get_template_fields(str(template_path))

        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(template_path))

        return {
            "template_id": template_id,
            "success": True,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": html_preview,
            "operation": "add_image_at_cursor",
            "image_width": f"{width} inches"
        }

    except HTTPException:
        raise
    except Exception as e:
        error_detail = f"Add image at cursor failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"=== /add-image-at-cursor ERROR ===")
        print(error_detail)
        print(f"=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)
