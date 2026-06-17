import logging
import os
import re
import uuid
import tempfile
import shutil
from functools import wraps
from pathlib import Path
from typing import Dict, Literal, Callable, Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
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
from smart_mail_merge_converter import SmartMailMergeConverter
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== HELPER FUNCTIONS =====

def save_and_regenerate_preview(editor: DocxFullEditor, template_path: str) -> tuple[list, str]:
    """Save template và regenerate HTML preview"""
    editor.save(str(template_path))
    fields = MergeExecutor().get_template_fields(str(template_path))
    html_preview = MailMergeProcessor()._generate_html_preview(str(template_path))

    return fields, html_preview


def validate_template_path(template_id: str) -> Path:
    """Validate template exists và return path"""
    template_path = TEMPLATE_DIR / f"{template_id}.docx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    return template_path


def handle_endpoint_errors(endpoint_name: str):
    """
    Decorator để xử lý lỗi chuẩn cho các endpoint.

    Tự động log traceback và raise HTTPException 500 với detail đầy đủ.
    HTTPException được pass-through để giữ status code gốc.

    Args:
        endpoint_name: Tên endpoint cho log (vd: "suggest placeholders", "batch update")
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # Pass-through HTTPException với status code gốc
                raise
            except Exception as e:
                # Log traceback và raise HTTPException 500 với detail đầy đủ
                error_detail = f"{endpoint_name} failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
                logger.error(f"=== /{endpoint_name.replace(' ', '-').lower()} ERROR ===\n{error_detail}\n=== END ERROR ===")
                raise HTTPException(status_code=500, detail=error_detail)
        return wrapper
    return decorator


def parse_json_list(raw_value: str | None) -> list[str]:
    """Parse a JSON array form field into a list of strings."""
    if not raw_value:
        return []

    parsed = json.loads(raw_value)
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON array")

    return [str(item) for item in parsed if item is not None]


def empty_gemini_usage() -> dict:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def resolve_ai_model(provider: str) -> str:
    if provider == "ollama":
        model = DEFAULT_OLLAMA_MODEL
        env_name = "OLLAMA_MODEL"
    elif provider == "vllm":
        model = DEFAULT_VLLM_MODEL
        env_name = "VLLM_MODEL"
    elif provider == "gemini":
        model = DEFAULT_GEMINI_MODEL
        env_name = "GEMINI_MODEL"
    elif provider == "finetuned":
        model = FINETUNED_BASE_MODEL
        env_name = "FINETUNED_BASE_MODEL"
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    clean_model = (model or "").strip()
    if not clean_model:
        raise ValueError(f"{env_name} is required when AI_PROVIDER={provider}")
    return clean_model


def create_ai_client() -> GeminiClient:
    return GeminiClient(
        GEMINI_API_KEY,
        provider=DEFAULT_AI_PROVIDER,
        model_name=resolve_ai_model(DEFAULT_AI_PROVIDER),
        ollama_base_url=OLLAMA_BASE_URL,
        openai_base_url=VLLM_BASE_URL,
        openai_api_key=VLLM_API_KEY,
        finetuned_path=FINETUNED_PATH,
        finetuned_base_model=FINETUNED_BASE_MODEL,
    )


def processor_for_ai() -> MailMergeProcessor:
    return MailMergeProcessor(
        gemini_api_key=GEMINI_API_KEY,
        ai_provider=DEFAULT_AI_PROVIDER,
        ai_model=resolve_ai_model(DEFAULT_AI_PROVIDER),
        ollama_base_url=OLLAMA_BASE_URL,
        openai_base_url=VLLM_BASE_URL,
        openai_api_key=VLLM_API_KEY,
        finetuned_path=FINETUNED_PATH,
        finetuned_base_model=FINETUNED_BASE_MODEL,
    )


def apply_batch_update_operations(
    template_id: str,
    template_path: Path,
    operations: list[dict],
    validate_only: bool = False,
    stop_on_error: bool = True,
) -> dict:
    """Apply DOCX edit operations atomically and return the standard response."""
    batch_request = BatchUpdateRequest(
        template_id=template_id,
        operations=operations,
        validate_only=validate_only,
        stop_on_error=stop_on_error,
    )

    results = {
        "template_id": batch_request.template_id,
        "total_operations": len(batch_request.operations),
        "successful": 0,
        "failed": 0,
        "operation_results": [],
        "validation_errors": [],
        "execution_errors": []
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        working_template_path = Path(tmpdir) / template_path.name
        shutil.copy2(template_path, working_template_path)
        editor = DocxFullEditor(str(working_template_path))

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
                if batch_request.stop_on_error:
                    break
                continue

            if batch_request.validate_only:
                results["successful"] += 1
                results["operation_results"].append({
                    "index": i,
                    "type": op.type,
                    "status": "validated"
                })
                continue

            try:
                execute_operation(editor, op)
            except Exception as e:
                error_msg = f"Op {i} ({op.type}): {str(e)}"
                results["failed"] += 1
                results["execution_errors"].append(error_msg)
                results["operation_results"].append({
                    "index": i,
                    "type": op.type,
                    "status": "failed",
                    "error": str(e)
                })
                if batch_request.stop_on_error:
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

        if results["validation_errors"]:
            return {
                **results,
                "success": False,
                "fields": [],
                "field_count": 0,
                "html_preview": "",
                "message": "Validation failed - no changes made",
            }

        if batch_request.validate_only:
            return {
                **results,
                "success": True,
                "fields": [],
                "field_count": 0,
                "html_preview": "",
                "message": "Validation passed - no changes made (validate_only mode)",
            }

        fields, html_preview = save_and_regenerate_preview(editor, str(working_template_path))
        shutil.copy2(working_template_path, template_path)

    return {
        **results,
        "success": results["failed"] == 0,
        "fields": fields,
        "field_count": len(fields),
        "html_preview": html_preview,
        "message": f"Batch update completed: {results['successful']} succeeded, {results['failed']} failed"
    }
def build_missing_fields(values: dict, fields: list[str], locked_fields: set[str] | None = None) -> list[str]:
    """Return unlocked fields that still do not have a concrete value."""
    locked_fields = locked_fields or set()
    return [
        field for field in fields
        if field not in locked_fields and not str(values.get(field, "")).strip()
    ]


def build_fill_status_message(
    missing_fields: list[str],
    updated_fields: list[str],
    corrected_fields: list[str] | None = None,
) -> str:
    corrected_fields = corrected_fields or []
    changed_fields = corrected_fields or updated_fields
    changed_preview = ", ".join(f"«{field}»" for field in changed_fields[:5])
    changed_suffix = "" if len(changed_fields) <= 5 else f" và {len(changed_fields) - 5} field khác"

    if missing_fields:
        missing_preview = ", ".join(f"«{field}»" for field in missing_fields[:8])
        suffix = "" if len(missing_fields) <= 8 else f" và {len(missing_fields) - 8} field khác"
        if corrected_fields:
            return f"Đã sửa {changed_preview}{changed_suffix}. Anh/chị vui lòng cung cấp thêm: {missing_preview}{suffix}."
        if updated_fields:
            return f"Đã ghi nhận thông tin mới. Anh/chị vui lòng cung cấp thêm: {missing_preview}{suffix}."
        return f"Chưa tìm thấy thông tin phù hợp. Anh/chị vui lòng cung cấp: {missing_preview}{suffix}."

    if corrected_fields:
        return f"Đã sửa {changed_preview}{changed_suffix}. Thông tin hiện đã đủ để tạo tài liệu."
    if updated_fields:
        return "Đã đủ thông tin để tạo tài liệu. Anh/chị có thể kiểm tra lại các giá trị và thực hiện merge."
    return "Các thông tin bắt buộc hiện đã đủ. Anh/chị có thể thực hiện merge."


# Setup paths
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATE_DIR = UPLOAD_DIR / "templates"
RESULT_DIR = UPLOAD_DIR / "results"
IMAGE_DIR = UPLOAD_DIR / "images"  # Directory for uploaded images
DRAFT_SESSIONS: dict[str, dict] = {}

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
DEFAULT_AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_VLLM_MODEL = os.getenv("VLLM_MODEL")
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8001/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")
FINETUNED_PATH = os.getenv("FINETUNED_PATH")
FINETUNED_BASE_MODEL = os.getenv("FINETUNED_BASE_MODEL")
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

if DEFAULT_AI_PROVIDER not in {"gemini", "ollama", "vllm", "finetuned"}:
    raise ValueError(f"Unsupported AI_PROVIDER: {DEFAULT_AI_PROVIDER}")

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
        "ai_provider": DEFAULT_AI_PROVIDER,
        "ai_model": resolve_ai_model(DEFAULT_AI_PROVIDER),
        "endpoints": {
            "root": "GET / (Health Check)",
            "convert": "POST /convert",
            "merge": "POST /merge",
            "download": "GET /download/{file_id}"
        }
    }


@app.post("/convert")
@handle_endpoint_errors("convert to template")
async def convert_to_template(
    file: UploadFile = File(...),
    auto_fill_tables: bool = Form(True),
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

        processor = processor_for_ai()
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
            "method": result.get("method", "smart_converter"),
            "ai_provider": result.get("ai_provider", DEFAULT_AI_PROVIDER),
            "ai_model": result.get("ai_model", resolve_ai_model(DEFAULT_AI_PROVIDER)),
            "ai_usage": result.get("ai_usage", result.get("gemini_usage", empty_gemini_usage())),
            "ai_usage_steps": result.get("ai_usage_steps", result.get("gemini_usage_steps", [])),
            "gemini_usage": result.get("gemini_usage", empty_gemini_usage()),
            "gemini_usage_steps": result.get("gemini_usage_steps", [])
        }

        return JSONResponse(content=response_data)

    finally:
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()


@app.post("/merge")
@handle_endpoint_errors("merge template")
async def merge_template(
    template_id: str = Form(...),
    context: str = Form(None),
    field_values: str = Form(None),
    active_fields: str = Form(None),
    locked_fields: str = Form(None),
):
    """Fill Mail Merge template with data

    Args:
        template_id: ID of template from /convert endpoint
        context: Text context with data to fill (optional, for Gemini extraction)
        field_values: JSON string of field-value pairs (optional, for direct values)
        active_fields: JSON string array of active fields (IGNORED when using context - Gemini extracts ALL fields)
        locked_fields: JSON string array of fields to keep as-is (not filled)

    Returns:
        JSON with result_id and download_url

    Note:
        When using context (Gemini extraction), ALL fields except locked_fields will be extracted.
        The active_fields parameter is ignored to prevent missing fields due to incomplete frontend data.
    """
    template_path = validate_template_path(template_id)
    gemini_usage = empty_gemini_usage()

    executor = MergeExecutor()
    # Get field names + template context in ONE pass. Documents over the page
    # threshold use compact heading-aware context instead of full text.
    template_fields, full_template_text, document_page_count = executor.get_template_fields_and_text(
        str(template_path),
        user_context=context or "",
    )


    # Determine data source
    if field_values:
        data = json.loads(field_values)

        # Ensure all required fields have values (empty string if missing)
        for field in template_fields:
            if field not in data:
                data[field] = ""

    elif context:
        # Use Gemini to extract from context
        gemini_client = create_ai_client()

        locked_f = set(parse_json_list(locked_fields))

        # Chỉ filter locked_fields - Gemini sẽ extract TẤT CẢ fields khác
        # Điều này đảm bảo KHÔNG bị thiếu field do frontend gửi thiếu active_fields
        if locked_f:
            template_fields = [f for f in template_fields if f not in locked_f]

        logger.debug("=== MERGE DEBUG ===")
        logger.debug(f"Template fields to extract: {template_fields}")
        logger.debug(f"Template context length: {len(full_template_text)} chars")
        logger.debug(f"Document page count: {document_page_count or 'unknown'}")

        data = gemini_client.extract_data_from_context(
            context=context,
            template_fields=template_fields,
            full_template_text=full_template_text,
            document_page_count=document_page_count,
        )
        logger.debug(f"Extracted data: {data}")
        logger.debug("=== END MERGE DEBUG ===")
        gemini_usage = gemini_client.get_usage_summary()
    else:
        data = {}

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
        "fields_filled": sum(1 for value in data.values() if str(value).strip()),
        "gemini_usage": gemini_usage if context else empty_gemini_usage()
    })


@app.post("/drafts/start")
@handle_endpoint_errors("start fill draft")
async def start_fill_draft(
    template_id: str = Form(...),
    locked_fields: str = Form(None),
):
    """Create a fill draft so users can provide data over multiple messages."""
    template_path = validate_template_path(template_id)
    executor = MergeExecutor()
    fields = executor.get_template_fields(str(template_path))
    locked_f = set(parse_json_list(locked_fields))
    values = {field: "" for field in fields}
    missing_fields = build_missing_fields(values, fields, locked_f)

    draft_id = str(uuid.uuid4())
    DRAFT_SESSIONS[draft_id] = {
        "draft_id": draft_id,
        "template_id": template_id,
        "fields": fields,
        "values": values,
        "messages": [],
    }

    return JSONResponse(content={
        "draft_id": draft_id,
        "template_id": template_id,
        "fields": fields,
        "values": values,
        "missing_fields": missing_fields,
        "assistant_message": build_fill_status_message(missing_fields, []),
        "gemini_usage": empty_gemini_usage(),
    })


@app.post("/drafts/{draft_id}/message")
@handle_endpoint_errors("continue fill draft")
async def continue_fill_draft(
    draft_id: str,
    message: str = Form(...),
    field_values: str = Form(None),
    locked_fields: str = Form(None),
):
    """Extract field additions or corrections from the newest user message."""
    draft = DRAFT_SESSIONS.get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    template_path = validate_template_path(draft["template_id"])
    fields = draft["fields"]
    values = dict(draft.get("values") or {})

    if field_values:
        values.update(json.loads(field_values))

    locked_f = set(parse_json_list(locked_fields))
    fields_to_extract = [field for field in fields if field not in locked_f]
    gemini_usage = empty_gemini_usage()
    extracted = {}
    updated_fields = []
    corrected_fields = []

    if message.strip() and fields_to_extract:
        executor = MergeExecutor()
        _, full_template_text, document_page_count = executor.get_template_fields_and_text(
            str(template_path),
            user_context=message,
        )

        gemini_client = create_ai_client()
        extracted = gemini_client.extract_data_from_context(
            context=message,
            template_fields=fields_to_extract,
            full_template_text=full_template_text,
            document_page_count=document_page_count,
            current_values=values,
        )
        gemini_usage = gemini_client.get_usage_summary()

        for field in fields_to_extract:
            value = str(extracted.get(field, "")).strip()
            if value:
                old_value = str(values.get(field, "")).strip()
                values[field] = value
                if old_value and old_value != value:
                    corrected_fields.append(field)
                elif not old_value:
                    updated_fields.append(field)

    missing_fields = build_missing_fields(values, fields, locked_f)
    assistant_message = build_fill_status_message(missing_fields, updated_fields, corrected_fields)

    draft["values"] = values
    draft["messages"].append({"role": "user", "content": message})
    draft["messages"].append({"role": "assistant", "content": assistant_message})

    return JSONResponse(content={
        "draft_id": draft_id,
        "values": values,
        "extracted": extracted,
        "updated_fields": updated_fields,
        "corrected_fields": corrected_fields,
        "missing_fields": missing_fields,
        "assistant_message": assistant_message,
        "gemini_usage": gemini_usage,
    })


@app.post("/drafts/{draft_id}/merge")
@handle_endpoint_errors("merge fill draft")
async def merge_fill_draft(
    draft_id: str,
    field_values: str = Form(None),
    locked_fields: str = Form(None)
):
    """Merge a completed draft with accumulated structured values."""
    draft = DRAFT_SESSIONS.get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    template_path = validate_template_path(draft["template_id"])
    fields = draft["fields"]
    values = dict(draft.get("values") or {})

    if field_values:
        values.update(json.loads(field_values))

    locked_f = set(parse_json_list(locked_fields))
    missing_fields = build_missing_fields(values, fields, locked_f)

    executor = MergeExecutor()
    result_path, result_id = executor.execute_merge(
        str(template_path),
        values,
        locked_fields=locked_f,
    )

    draft["values"] = values

    return JSONResponse(content={
        "result_id": result_id,
        "download_url": f"/download/{result_id}",
        "fields_filled": sum(1 for value in values.values() if str(value).strip()),
        "missing_fields": missing_fields,
        "warning_message": build_fill_status_message(missing_fields, []) if missing_fields else "",
        "gemini_usage": empty_gemini_usage(),
    })


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
@handle_endpoint_errors("preview file")
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


@app.post("/suggest-placeholders")
@handle_endpoint_errors("suggest placeholders")
async def suggest_placeholders(
    template_id: str = Form(...),
):
    """Analyze template with AI to detect missing placeholders

    Args:
        template_id: ID of template to analyze

    Returns:
        JSON with AI suggestions for missing placeholders
    """
    template_path = validate_template_path(template_id)

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
    gemini_client = create_ai_client()
    analysis = gemini_client.analyze_document_for_placeholders(
        structured_content,
        existing_fields
    )

    suggestions = analysis.get("suggestions", [])
    gemini_usage = gemini_client.get_usage_summary()

    return {
        "template_id": template_id,
        "suggestions": suggestions,
        "gemini_usage": gemini_usage,
    }


@app.post("/apply-suggestions")
@handle_endpoint_errors("apply AI suggestions")
async def apply_ai_suggestions(
    template_id: str = Form(...),
    suggestions: str = Form(...),  # JSON string of suggestions to apply
):
    """Apply AI-generated placeholder suggestions to template

    Args:
        template_id: ID of template to update
        suggestions: JSON array of suggestions to apply

    Returns:
        JSON with update results
    """
    template_path = validate_template_path(template_id)

    suggestions_list = json.loads(suggestions)

    if not suggestions_list:
        raise HTTPException(
            status_code=400,
            detail="No suggestions provided"
        )

    # Apply each suggestion
    processor = processor_for_ai()
    results = {
        "template_id": template_id,
        "total_suggestions": len(suggestions_list),
        "successful": 0,
        "failed": 0,
        "applied_fields": [],
        "gemini_usage": empty_gemini_usage()
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

    # Get updated field list and HTML preview using helper function
    editor = DocxFullEditor(str(template_path))
    updated_fields, html_preview = save_and_regenerate_preview(editor, str(template_path))

    results["updated_field_count"] = len(updated_fields)
    results["updated_fields"] = updated_fields
    results["html_preview"] = html_preview

    return results


@app.post("/semantic-edit")
@handle_endpoint_errors("semantic document edit")
async def semantic_document_edit(
    template_id: str = Form(...),
    instruction: str = Form(""),
    validate_only: bool = Form(False),
    planned_edits: str = Form(None),
):
    """Edit existing document text from a natural-language instruction.

    Gemini identifies the target text and returns text replacement operations.
    The backend applies those operations directly to DOCX runs so existing
    formatting is preserved.
    """
    template_path = validate_template_path(template_id)
    clean_instruction = (instruction or "").strip()
    if not clean_instruction and not planned_edits:
        raise HTTPException(status_code=400, detail="instruction is required")

    processor = MailMergeProcessor()
    structured_content = processor.extract_structured_content(str(template_path))
    if not structured_content:
        raise HTTPException(status_code=500, detail="Failed to extract content from template")

    gemini_usage = empty_gemini_usage()
    warnings = []

    if planned_edits:
        parsed_edits = json.loads(planned_edits)
        if not isinstance(parsed_edits, list):
            raise HTTPException(status_code=400, detail="planned_edits must be a JSON array")
        edits = [
            {
                "block_index": int(edit.get("block_index")),
                "old_text": str(edit.get("old_text") or "").strip(),
                "new_text": str(edit.get("new_text") or ""),
                "reason": str(edit.get("reason") or ""),
            }
            for edit in parsed_edits
            if edit.get("block_index") is not None and str(edit.get("old_text") or "").strip()
        ]
    else:
        gemini_client = create_ai_client()
        plan = gemini_client.plan_document_text_edits(clean_instruction, structured_content)
        edits = plan.get("edits", [])
        warnings = plan.get("warnings", [])
        gemini_usage = gemini_client.get_usage_summary()

    if not edits:
        fields = MergeExecutor().get_template_fields(str(template_path))
        return {
            "template_id": template_id,
            "success": False,
            "message": "Gemini không tìm được vị trí sửa đủ chắc chắn.",
            "planned_edits": [],
            "warnings": warnings,
            "gemini_usage": gemini_usage,
            "fields": fields,
            "field_count": len(fields),
            "html_preview": MailMergeProcessor()._generate_html_preview(str(template_path)),
        }

    operations = [
        {
            "type": "update_text",
            "block_index": edit["block_index"],
            "old_text": edit["old_text"],
            "new_text": edit["new_text"],
            "description": edit.get("reason", ""),
        }
        for edit in edits
    ]

    batch_result = apply_batch_update_operations(
        template_id=template_id,
        template_path=template_path,
        operations=operations,
        validate_only=validate_only,
        stop_on_error=True,
    )

    return {
        **batch_result,
        "planned_edits": edits,
        "warnings": warnings,
        "gemini_usage": gemini_usage,
        "message": (
            batch_result.get("message")
            if not batch_result.get("success")
            else "Semantic edit validated"
            if validate_only
            else f"Đã áp dụng {batch_result.get('successful', 0)} chỉnh sửa"
        ),
    }


@app.post("/suggest-field-name")
@handle_endpoint_errors("suggest field name")
async def suggest_field_name(
    template_id: str = Form(...),
    block_index: int = Form(...),
    para_in_cell: int = Form(None),
):
    """Suggest a field name based on the selected block's text

    Args:
        template_id: ID of template
        block_index: Index of content block to extract text from
        para_in_cell: Optional paragraph index within cell

    Returns:
        JSON with suggested field name
    """
    template_path = validate_template_path(template_id)

    # Initialize processor
    processor = processor_for_ai()

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


@app.post("/get-selection-format")
@handle_endpoint_errors("get selection format")
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
    template_path = validate_template_path(template_id)

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


# Table operations now handled by /batch-update endpoint
# Use: batchUpdate(templateId, [{type: "add_table_row", ...}])

@app.get("/get-cell-format")
@handle_endpoint_errors("get cell format")
async def get_cell_format(
    template_id: str,
    table_index: int,
    row_index: int,
    col_index: int
):
    """Get current formatting of a table cell

    Returns background color, vertical alignment, and horizontal alignment
    """
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


@app.post("/add-image-at-cursor")
@handle_endpoint_errors("add image at cursor")
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
    template_path = validate_template_path(template_id)

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
    with open(image_path, "wb") as buffer:
        content = await image_file.read()
        buffer.write(content)
    logger.debug(f" Image saved to: {image_path}")

    # Open and edit template
    editor = DocxFullEditor(str(template_path))

    # Map block_index to paragraph_index
    paragraph_index = editor.get_paragraph_index_from_block(block_index)
    if paragraph_index is None:
        raise HTTPException(status_code=400, detail=f"Invalid block_index: {block_index}")

    logger.debug(f" Mapped block_index={block_index} to paragraph_index={paragraph_index}")

    # Add image at cursor position
    editor.add_image_at_cursor(
        paragraph_index=paragraph_index,
        offset=offset,
        image_path=str(image_path),
        width=width
    )
    logger.info(f" Successfully added image at cursor position")

    # Save and regenerate preview using helper function
    fields, html_preview = save_and_regenerate_preview(editor, str(template_path))

    return {
        "template_id": template_id,
        "success": True,
        "fields": fields,
        "field_count": len(fields),
        "html_preview": html_preview,
        "operation": "add_image_at_cursor",
        "image_width": f"{width} inches"
    }


# =============================================================================
# PYDANTIC MODELS FOR TABLE EXPANSION
# =============================================================================

class TableExpansionPreviewRequest(BaseModel):
    """Request model cho table expansion preview"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
                "context_data": {
                    "thong_tin_nha_dau_tu": ["ho_ten", "ngay_sinh", "quoc_tich"],
                    "ty_le_gop_von": ["nha_dau_tu_1", "nha_dau_tu_2", "nha_dau_tu_3"]
                },
                "auto_expand": True
            }
        }
    )

    template_id: str = Field(..., description="Template ID from /convert endpoint")
    context_data: Dict[str, List[str]] = Field(..., description="Context data với field names organized by sections")
    auto_expand: bool = Field(True, description="Tự động expand tables nếu cần")


class TableExpansionRequest(BaseModel):
    """Request model cho merge với table expansion"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
                "context_data": {
                    "thong_tin_nha_dau_tu": ["ho_ten", "ngay_sinh", "quoc_tich"],
                    "ty_le_gop_von": ["nha_dau_tu_1", "nha_dau_tu_2", "nha_dau_tu_3"]
                },
                "field_values": {
                    "ho_ten": "Nguyễn Văn A",
                    "ngay_sinh": "01/01/1990"
                },
                "auto_expand": True,
                "preview_only": False
            }
        }
    )

    template_id: str = Field(..., description="Template ID from /convert endpoint")
    context_data: Dict[str, List[str]] = Field(..., description="Context data organized by sections")
    field_values: Optional[Dict[str, str]] = Field(None, description="Optional field values để merge")
    auto_expand: bool = Field(True, description="Tự động expand tables nếu cần")
    preview_only: bool = Field(False, description="Nếu True, chỉ preview mà không execute")


class TableAnalysis(BaseModel):
    """Model cho table analysis result"""
    table_index: int
    total_rows: int
    data_rows: int
    columns: int
    empty_cells: int
    needs_expansion: bool
    rows_to_add: int
    empty_cells_after_expansion: int


class TableExpansionPreviewResponse(BaseModel):
    """Response model cho table expansion preview"""
    template_id: str
    needs_expansion: bool
    total_fields_required: int
    table_fields_required: int
    tables_analysis: List[TableAnalysis]
    summary: str


class TableExpansionResponse(BaseModel):
    """Response model cho merge với expansion"""
    template_id: str
    result_id: Optional[str] = None
    success: Optional[bool] = None  # None for preview mode
    message: str
    tables_expanded: int
    total_rows_added: int
    fields_filled: int
    download_url: Optional[str] = None


# =============================================================================
# BATCH UPDATE ENDPOINT
# =============================================================================

@app.post("/batch-update")
@handle_endpoint_errors("batch update")
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
            {"type": "rename_placeholder", "old_name": "ho_ten", "new_name": "ten_day_du", "occurrence_index": 0},
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

        logger.info(" ===== PHASE 1: VALIDATE ONLY =====")

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

            results["operation_results"].append({
                "index": i,
                "type": op.type,
                "status": "validated"
            })
            logger.debug(f" Op {i} ({op.type}): ✓ VALIDATED")

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
            results["successful"] = len(batch_request.operations) - len(results["validation_errors"])

            return {
                **results,
                "success": True,
                "message": "Validation passed - no changes made (validate_only mode)",
                "fields": [],
                "field_count": 0,
                "html_preview": ""
            }

        logger.info(" ===== PHASE 2: EXECUTE =====")
        results["operation_results"] = []

        for i, op in enumerate(batch_request.operations):
            try:
                execute_operation(editor, op)
            except Exception as e:
                error_msg = f"Op {i} ({op.type}): {str(e)}"
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
                "status": "executed"
            })
            logger.debug(f" Op {i} ({op.type}): ✓ EXECUTED")

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


# =============================================================================
# TABLE EXPANSION ENDPOINTS
# =============================================================================

@app.post("/api/preview-table-expansion")
@handle_endpoint_errors("preview table expansion")
async def preview_table_expansion(request: TableExpansionPreviewRequest):
    """
    Preview table expansion plan trước khi execute

    Analyzes context data và table structure để determine:
    - Có cần expansion không?
    - Bao nhiêu rows cần thêm?
    - Bảng nào sẽ được expanded?

    Args:
        request: TableExpansionPreviewRequest với template_id và context_data

    Returns:
        TableExpansionPreviewResponse với detailed analysis
    """
    template_path = validate_template_path(request.template_id)

    # Initialize converter
    converter = SmartMailMergeConverter(
        str(template_path),
        gemini_api_key=GEMINI_API_KEY,
        ai_provider=DEFAULT_AI_PROVIDER,
        ai_model=resolve_ai_model(DEFAULT_AI_PROVIDER),
        ollama_base_url=OLLAMA_BASE_URL,
        openai_base_url=VLLM_BASE_URL,
        openai_api_key=VLLM_API_KEY,
    )

    # Analyze context requirements
    requirements = converter._analyze_context_requirements(request.context_data)

    # Analyze each table
    tables_analysis = []
    total_rows_to_add = 0
    needs_expansion = False

    for table_idx, table in enumerate(converter.doc.tables):
        structure = converter._get_table_structure(table)
        empty_cells = converter._count_empty_cells_in_table(table)

        # Determine if this table needs expansion
        # Use table_fields if available, otherwise use total_fields
        table_required_fields = len(requirements["table_fields"]) if requirements["table_fields"] else 0

        # For preview, we'll show what WOULD happen if we expanded
        # Calculate expansion needed
        if empty_cells < table_required_fields:
            expansion_result = converter._expand_table_for_context(table, table_required_fields)
            needs_expansion_table = True
        else:
            expansion_result = {
                "rows_added": 0,
                "total_rows": len(table.rows),
                "empty_cells": empty_cells
            }
            needs_expansion_table = False

        if needs_expansion_table:
            needs_expansion = True
            total_rows_to_add += expansion_result["rows_added"]

        table_analysis = TableAnalysis(
            table_index=table_idx,
            total_rows=structure["data_rows"] + (1 if structure["has_header"] else 0),
            data_rows=structure["data_rows"],
            columns=structure["columns"],
            empty_cells=empty_cells,
            needs_expansion=needs_expansion_table,
            rows_to_add=expansion_result["rows_added"],
            empty_cells_after_expansion=expansion_result["empty_cells"]
        )
        tables_analysis.append(table_analysis)

    # Generate summary
    if needs_expansion:
        summary = f"Cần mở rộng {total_rows_to_add} rows across {len([t for t in tables_analysis if t.needs_expansion])} tables"
    else:
        summary = "Tất cả bảng đã có đủ chỗ, không cần mở rộng"

    return TableExpansionPreviewResponse(
        template_id=request.template_id,
        needs_expansion=needs_expansion,
        total_fields_required=requirements["total_fields"],
        table_fields_required=len(requirements["table_fields"]),
        tables_analysis=tables_analysis,
        summary=summary
    )


@app.post("/api/merge-with-expansion")
@handle_endpoint_errors("merge with table expansion")
async def merge_with_table_expansion(request: TableExpansionRequest):
    """
    Execute merge với automatic table expansion

    Process:
    1. Analyze context và determine expansion needs
    2. Create working copy of template
    3. Expand tables if needed
    4. Execute merge
    5. Save result

    Args:
        request: TableExpansionRequest với template_id, context_data, và options

    Returns:
        TableExpansionResponse với result details và download URL
    """
    template_path = validate_template_path(request.template_id)

    # Analyze context requirements
    converter = SmartMailMergeConverter(
        str(template_path),
        gemini_api_key=GEMINI_API_KEY,
        ai_provider=DEFAULT_AI_PROVIDER,
        ai_model=resolve_ai_model(DEFAULT_AI_PROVIDER),
        ollama_base_url=OLLAMA_BASE_URL,
        openai_base_url=VLLM_BASE_URL,
        openai_api_key=VLLM_API_KEY,
    )
    requirements = converter._analyze_context_requirements(request.context_data)

    if request.preview_only:
        # Preview mode - just return what would happen
        preview = await preview_table_expansion(
            TableExpansionPreviewRequest(
                template_id=request.template_id,
                context_data=request.context_data,
                auto_expand=request.auto_expand
            )
        )
        return TableExpansionResponse(
            template_id=request.template_id,
            success=None,
            message="Preview mode - no changes made",
            tables_expanded=0,
            total_rows_added=0,
            fields_filled=0,
            download_url=None
        )

    # Execute mode
    logger.info(f" ===== MERGE WITH EXPANSION START =====")
    logger.info(f" Template ID: {request.template_id}")
    logger.info(f" Total fields required: {requirements['total_fields']}")
    logger.info(f" Table fields required: {len(requirements['table_fields'])}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create working copy
        working_template = Path(tmpdir) / template_path.name
        shutil.copy2(template_path, working_template)

        # Re-initialize converter with working copy
        converter = SmartMailMergeConverter(
            str(working_template),
            gemini_api_key=GEMINI_API_KEY,
            ai_provider=DEFAULT_AI_PROVIDER,
            ai_model=resolve_ai_model(DEFAULT_AI_PROVIDER),
            ollama_base_url=OLLAMA_BASE_URL,
            openai_base_url=VLLM_BASE_URL,
            openai_api_key=VLLM_API_KEY,
        )

        # Expand tables if needed
        tables_expanded = 0
        total_rows_added = 0

        if request.auto_expand:
            logger.info(" ===== EXPANDING TABLES =====")

            for table_idx, table in enumerate(converter.doc.tables):
                structure = converter._get_table_structure(table)
                empty_cells = converter._count_empty_cells_in_table(table)

                # Determine required fields for this table
                table_required_fields = len(requirements["table_fields"]) if requirements["table_fields"] else 0

                if empty_cells < table_required_fields and table_required_fields > 0:
                    expansion_result = converter._expand_table_for_context(table, table_required_fields)

                    if expansion_result["rows_added"] > 0:
                        tables_expanded += 1
                        total_rows_added += expansion_result["rows_added"]
                        logger.info(f" Table {table_idx}: Added {expansion_result['rows_added']} rows")
                        logger.info(f"   Before: {structure['data_rows']} data rows × {structure['columns']} cols")
                        logger.info(f"   After: {expansion_result['total_rows']} total rows")

        # Save expanded template using doc object directly
        converter.doc.save(str(working_template))

        # Execute merge
        logger.info(" ===== EXECUTING MERGE =====")

        executor = MergeExecutor()
        template_fields = executor.get_template_fields(str(working_template))

        # Determine data source
        if request.field_values:
            data = request.field_values

            # Ensure all required fields have values
            for field in template_fields:
                if field not in data:
                    data[field] = ""

            logger.info(f" Using provided field_values: {len(data)} fields")
        else:
            raise HTTPException(
                status_code=400,
                detail="field_values must be provided for merge"
            )

        # Execute merge
        result_path, result_id = executor.execute_merge(
            str(working_template),
            data,
            locked_fields=set()
        )

        # Note: execute_merge already saves to RESULT_DIR, so result_path is the final location
        # No need to copy again

        logger.info(f" ===== MERGE COMPLETE =====")
        logger.info(f" Tables expanded: {tables_expanded}")
        logger.info(f" Total rows added: {total_rows_added}")
        logger.info(f" Fields filled: {sum(1 for v in data.values() if str(v).strip())}")

    return TableExpansionResponse(
        template_id=request.template_id,
        result_id=result_id,
        success=True,
        message=f"Merge completed: {tables_expanded} tables expanded, {total_rows_added} rows added",
        tables_expanded=tables_expanded,
        total_rows_added=total_rows_added,
        fields_filled=sum(1 for v in data.values() if str(v).strip()),
        download_url=f"/download/{result_id}"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
