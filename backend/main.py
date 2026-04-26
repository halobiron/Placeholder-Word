import logging
import os
import re
import uuid
import tempfile
import shutil
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
from batch_update_models import BatchUpdateRequest, Operation, BatchUpdateResponse
from batch_operations import validate_operation, execute_operation
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== HELPER FUNCTIONS =====

def save_and_regenerate_preview(editor: DocxFullEditor, template_path: str) -> tuple[list, str]:
    """Save template và regenerate HTML preview

    Args:
        editor: DocxFullEditor instance
        template_path: Path to save template

    Returns:
        Tuple of (fields, html_preview)
    """
    editor.save(str(template_path))

    executor = MergeExecutor()
    fields = executor.get_template_fields(str(template_path))

    processor = MailMergeProcessor()
    html_preview = processor._generate_html_preview(str(template_path))

    return fields, html_preview


def validate_template_path(template_id: str) -> Path:
    """Validate template exists và return path

    Args:
        template_id: Template identifier

    Returns:
        Path object to template

    Raises:
        HTTPException: If template not found
    """
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    return template_path


def handle_endpoint_error(endpoint_name: str, error: Exception) -> HTTPException:
    """Standard error handling với traceback logging"""
    error_detail = f"{endpoint_name} failed: {str(error)}\n\nTraceback:\n{traceback.format_exc()}"
    logger.error(f"=== /{endpoint_name.replace(' ', '-').lower()} ERROR ===\n{error_detail}\n=== END ERROR ===")
    return HTTPException(status_code=500, detail=error_detail)


def parse_json_list(raw_value: str | None) -> list[str]:
    """Parse a JSON array form field into a list of strings."""
    if not raw_value:
        return []

    parsed = json.loads(raw_value)
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON array")

    return [str(item) for item in parsed if item is not None]


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
            logger.error(f"Create directory failed: {e}")

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
async def convert_to_template(
    file: UploadFile = File(...),
    auto_fill_tables: bool = Form(True)
):
    """Upload .docx and convert to Mail Merge template

    Args:
        file: Uploaded .docx file
        auto_fill_tables: Auto-fill placeholders in empty table cells (default: True)

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
        result = processor.convert_to_mail_merge(str(temp_path), str(output_path), auto_fill_tables=auto_fill_tables)

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
    active_fields: str = Form(None),
    locked_fields: str = Form(None)
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
        template_field_metadata = executor.get_template_field_metadata(str(template_path))
        template_fields = [item["field_name"] for item in template_field_metadata]

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
            
            active_f = set(parse_json_list(active_fields))
            locked_f = set(parse_json_list(locked_fields))

            if active_f:
                template_field_metadata = [
                    item for item in template_field_metadata if item["field_name"] in active_f
                ]
            if locked_f:
                template_field_metadata = [
                    item for item in template_field_metadata if item["field_name"] not in locked_f
                ]
            template_fields = [item["field_name"] for item in template_field_metadata]

            logger.debug("=== MERGE DEBUG ===")
            logger.debug(f"Template fields to extract: {template_fields}")
            data = gemini_client.extract_data_from_context(
                context,
                template_fields,
                template_field_metadata=template_field_metadata,
            )
            logger.debug(f"Extracted data: {data}")
            logger.debug("=== END MERGE DEBUG ===")
        else:
            raise HTTPException(
                status_code=400,
                detail="Either 'context' or 'field_values' must be provided"
            )

        # Execute merge
        locked_f = set(parse_json_list(locked_fields))
        result_path, result_id = executor.execute_merge(
            str(template_path),
            data,
            locked_fields=locked_f
        )

        return JSONResponse(content={
            "result_id": result_id,
            "download_url": f"/download/{result_id}",
            "fields_filled": sum(1 for value in data.values() if str(value).strip())
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


@app.get("/preview/{file_id}")
async def preview_file(file_id: str):
    """Get HTML preview of template or result

    Args:
        file_id: ID of template or result file

    Returns:
        JSON with html_preview and file_type
    """
    # Try RESULT_DIR first, then TEMPLATE_DIR
    result_path = RESULT_DIR / f"{file_id}.docx"
    template_path = TEMPLATE_DIR / f"{file_id}.docx"

    file_path = None
    file_type = None

    if result_path.exists():
        file_path = result_path
        file_type = "result"
    elif template_path.exists():
        file_path = template_path
        file_type = "template"
    else:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")

    try:
        # Generate HTML preview
        processor = MailMergeProcessor()
        html_preview = processor._generate_html_preview(str(file_path))

        # Get fields if it's a template
        fields = []
        if file_type == "template":
            executor = MergeExecutor()
            fields = executor.get_template_fields(str(file_path))

        return JSONResponse(content={
            "file_id": file_id,
            "file_type": file_type,
            "html_preview": html_preview,
            "fields": fields
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


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

        # Get updated field list and HTML preview
        executor = MergeExecutor()
        updated_fields = executor.get_template_fields(str(template_path))

        # Generate HTML preview with updated placeholders
        html_preview = processor._generate_html_preview(str(template_path))

        results["updated_field_count"] = len(updated_fields)
        results["updated_fields"] = updated_fields
        results["html_preview"] = html_preview

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



@app.post("/get-selection-format")
async def get_selection_format(
    template_id: str = Form(...),
    selected_text: str = Form(...),
    block_index: int = Form(None),
    offset: int = Form(None),
    end_offset: int = Form(None),
    para_in_cell: int = Form(None)
):
    """
    Extract accurate formatting information for selected text from DOCX

    Args:
        template_id: Template ID
        selected_text: Text to extract format from
        block_index: Block index in HTML preview (for precision, optional)
        offset: Character offset within paragraph for precise targeting (optional)
        end_offset: End character offset for precise targeting (optional)
        para_in_cell: Paragraph index within table cell (optional)

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
        editor = DocxFullEditor(str(template_path))

        # Map block_index to paragraph_index if provided
        actual_para_index = None
        if block_index is not None:
            # CRITICAL FIX: For table cells with para_in_cell, use get_table_cell_paragraph_index
            # This correctly maps to the specific paragraph within the cell, not just the first one
            if para_in_cell is not None:
                actual_para_index = editor.get_table_cell_paragraph_index(block_index, para_in_cell)
            else:
                actual_para_index = editor.get_paragraph_index_from_block(block_index)

        # Get format using offset (frontend always provides this)
        format_info = editor.get_format(
            paragraph_index=actual_para_index,
            offset=offset,
            end_offset=end_offset,
            para_in_cell=para_in_cell
        ) or {}

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
        logger.error("=== /get-selection-format ERROR ===")
        logger.error(error_detail)
        logger.error("=== END ERROR ===")
        raise HTTPException(status_code=500, detail=error_detail)


# Table operations now handled by /batch-update endpoint
# Use: batchUpdate(templateId, [{type: "add_table_row", ...}])

@app.get("/get-cell-format")
async def get_cell_format(
    template_id: str,
    table_index: int,
    row_index: int,
    col_index: int
):
    """Get current formatting of a table cell

    Returns background color, vertical alignment, and horizontal alignment
    """
    try:
        # Validate required parameters
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")

        # Validate template exists
        template_path = validate_template_path(template_id)

        # Create editor
        editor = DocxFullEditor(str(template_path))

        # Get cell format
        cell_format = editor.get_cell_format(table_index, row_index, col_index)

        if cell_format is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid table_index, row_index, or col_index"
            )

        return {
            "template_id": template_id,
            "table_index": table_index,
            "row_index": row_index,
            "col_index": col_index,
            "format": cell_format
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get cell format error: {str(e)}")
        raise handle_endpoint_error("Get cell format", e)


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

        logger.info(f" add_image_at_cursor called: template_id={template_id}, block_index={block_index}, offset={offset}, width={width}")

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
            logger.debug(f" Image saved to: {image_path}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")

        # Open and edit template
        editor = DocxFullEditor(str(template_path))

        # Map block_index to paragraph_index
        paragraph_index = editor.get_paragraph_index_from_block(block_index)
        if paragraph_index is None:
            raise HTTPException(status_code=400, detail=f"Invalid block_index: {block_index}")

        logger.debug(f" Mapped block_index={block_index} to paragraph_index={paragraph_index}")

        # Add image at cursor position
        try:
            editor.add_image_at_cursor(
                paragraph_index=paragraph_index,
                offset=offset,
                image_path=str(image_path),
                width=width
            )
            logger.info(f" Successfully added image at cursor position")
        except Exception as e:
            error_detail = f"Failed to add image at cursor: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error("=== add_image_at_cursor ERROR ===")
            logger.error(error_detail)
            logger.error("=== END ERROR ===")
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
        raise handle_endpoint_error("Add image at cursor", e)


# =============================================================================
# BATCH UPDATE ENDPOINT
# =============================================================================

@app.post("/batch-update")
async def batch_update(request: Request):
    """
    Universal batch update endpoint - executes ALL operations in a single atomic transaction

    This endpoint unifies all DOCX editing operations into one coherent system:
    - Placeholder operations: rename, delete, add
    - Text operations: update, delete range
    - Formatting operations: format text, format paragraph
    - Structural operations: add/delete paragraphs, page breaks
    - Table operations: add/delete rows/columns, format cells, add tables
    - Image operations: add images at cursor or document end
    - Hyperlink operations: add hyperlinks to text ranges

    Features:
    - Atomic: All operations succeed or all fail (transaction)
    - Validation: Pre-flight validation before execution
    - Efficient: Single file save (not N saves for N operations)
    - Debuggable: Detailed operation results with status tracking
    - Flexible: validate_only mode for testing without executing

    Request Body (JSON):
    {
        "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
        "operations": [
            {"type": "rename_placeholder", "old_name": "ho_ten", "new_name": "ten_day_du"},
            {"type": "delete_placeholder", "field_name": "dia_chi_cu"},
            {"type": "update_text", "block_index": 5, "old_text": "Hello", "new_text": "Hi"},
            {"type": "format_text", "block_index": 10, "selected_text": "Important",
             "format_config": {"bold": true, "color": "FF0000"}}
        ],
        "validate_only": false,
        "stop_on_error": true
    }

    Returns:
    {
        "template_id": "...",
        "success": true,
        "total_operations": 4,
        "successful": 4,
        "failed": 0,
        "operation_results": [...],
        "fields": [...],
        "html_preview": "..."
    }
    """
    try:
        # Parse request body as JSON
        request_data = await request.json()

        # Validate and parse request
        batch_request = BatchUpdateRequest(**request_data)

        template_path = validate_template_path(batch_request.template_id)

        results = {
            "template_id": batch_request.template_id,
            "total_operations": len(batch_request.operations),
            "successful": 0,
            "failed": 0,
            "operation_results": [],
            "validation_errors": [],
            "execution_errors": []
        }

        logger.info(f" ===== BATCH UPDATE START =====")
        logger.info(f" Template ID: {batch_request.template_id}")
        logger.info(f" Total operations: {len(batch_request.operations)}")
        logger.info(f" Validate only: {batch_request.validate_only}")
        logger.info(f" Stop on error: {batch_request.stop_on_error}")

        with tempfile.TemporaryDirectory() as tmpdir:
            working_template_path = Path(tmpdir) / template_path.name
            shutil.copy2(template_path, working_template_path)
            editor = DocxFullEditor(str(working_template_path))

            logger.info(" ===== PHASE 1: VALIDATE AND APPLY =====")

            for i, op in enumerate(batch_request.operations):
                try:
                    validate_operation(editor, op)
                except ValueError as e:
                    error_msg = f"Op {i} ({op.type}): {str(e)}"
                    results["validation_errors"].append(error_msg)
                    results["operation_results"].append({
                        "index": i,
                        "type": op.type,
                        "status": "validation_failed",
                        "error": str(e)
                    })
                    logger.debug(f" Op {i} ({op.type}): ✗ VALIDATION FAILED - {str(e)}")
                    if batch_request.stop_on_error:
                        break
                    continue

                try:
                    execute_operation(editor, op)
                except Exception as e:
                    error_msg = f"Op {i} ({op.type}): {str(e)}"
                    if batch_request.validate_only:
                        results["validation_errors"].append(error_msg)
                        results["operation_results"].append({
                            "index": i,
                            "type": op.type,
                            "status": "validation_failed",
                            "error": str(e)
                        })
                    else:
                        results["failed"] += 1
                        results["execution_errors"].append(error_msg)
                        results["operation_results"].append({
                            "index": i,
                            "type": op.type,
                            "status": "failed",
                            "error": str(e)
                        })
                    logger.debug(f" Op {i} ({op.type}): ✗ EXECUTION FAILED - {str(e)}")
                    if batch_request.stop_on_error:
                        if batch_request.validate_only:
                            break
                        raise HTTPException(
                            status_code=500,
                            detail={
                                "error": "Batch update failed",
                                "failed_operation": error_msg,
                                "message": f"Operation {i} failed during execution."
                            }
                        )
                    continue

                results["successful"] += 1
                results["operation_results"].append({
                    "index": i,
                    "type": op.type,
                    "status": "validated" if batch_request.validate_only else "executed"
                })
                logger.debug(f" Op {i} ({op.type}): ✓ SUCCESS")

            if results["validation_errors"]:
                logger.info(" ===== VALIDATION FAILED =====")
                logger.info(f" Validation errors: {len(results['validation_errors'])}")

                return JSONResponse(
                    status_code=400,
                    content={
                        **results,
                        "success": False,
                        "message": "Validation failed - no changes made",
                        "fields": [],
                        "field_count": 0,
                        "html_preview": ""
                    }
                )

            if batch_request.validate_only:
                logger.info(" ===== VALIDATE ONLY MODE - SKIPPING SAVE =====")

                return {
                    **results,
                    "success": True,
                    "message": "Validation passed - no changes made (validate_only mode)",
                    "fields": [],
                    "field_count": 0,
                    "html_preview": ""
                }

            # =============================================================================
            # PHASE 2: SAVE & REGENERATE
            # =============================================================================
            logger.info(" ===== PHASE 2: SAVE & REGENERATE =====")

            # Save updated template in the isolated working copy first, then
            # commit the final file back to the real template path.
            fields, html_preview = save_and_regenerate_preview(editor, str(working_template_path))
            shutil.copy2(working_template_path, template_path)

        logger.info(f" ===== BATCH UPDATE COMPLETE =====")
        logger.info(f" Successful: {results['successful']}")
        logger.info(f" Failed: {results['failed']}")
        logger.info(f" Total fields: {len(fields)}")

        return {
            **results,
            "success": results["failed"] == 0,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": html_preview,
            "message": f"Batch update completed: {results['successful']} succeeded, {results['failed']} failed"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f" ===== BATCH UPDATE FAILED =====")
        logger.error(f" {str(e)}")
        logger.debug(f"[TRACEBACK] {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Batch update failed: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
