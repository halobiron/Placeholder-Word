# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Mail Merge Placeholder System** - A demo web application that converts Word documents with blank spaces (dots, underscores) into Microsoft Word Mail Merge templates, then fills them with AI-generated data.

**Key Purpose**: This standalone demo is designed for easy integration into `ai-server-xbot` after successful implementation.

**Language**: Vietnamese language support is a first-class concern. All placeholder detection, field naming, and context analysis must handle Vietnamese text with proper accents and patterns.

## Architecture

Detailed in docs/

## Tech Stack

### Backend
- **FastAPI** (Python 3.10+) - Standalone for demo, integrates into `ai-server-xbot`
- **python-docx** + **lxml** - DOCX manipulation with XML surgical injection
- **docx-mailmerge2** (v1.0.1) - Mail merge execution
- **Gemini API** - Smart field naming and context analysis

### Frontend
- **React** + **Vite**
- **TailwindCSS** - Styling
- **React Dropzone** - File upload

## Project Structure

```
placeholder/
├── backend/                    # FastAPI standalone (not yet created)
│   ├── main.py                # FastAPI app
│   ├── mail_merge_processor.py # Core conversion logic
│   ├── gemini_client.py        # Gemini integration
│   └── requirements.txt
├── frontend/                   # React + Vite (not yet created)
│   └── src/
│       ├── App.jsx
│       ├── components/
│       └── api.js
├── docs
│   ├── ARCHITECTURE.md             # This file
│   ├── INSTRUCTIONS.md             # Detailed implementation specs
└── CLAUDE.md                   # This file
```

## Development Commands

**Note**: This environment has ripgrep permission issues. Use basic bash commands:

```bash
# Find files
find . -name "*.py" -o -name "*.jsx"

# List directory contents
ls -la

# Read files
cat file.txt

# Search in files (basic grep)
grep -r "pattern" . --include="*.py"
```

## Integration Path to ai-server-xbot

After successful demo implementation, port code as follows:

```
ai-server-xbot/modules/
├── utils/
│   └── mail_merge/
│       ├── processor.py        # From mail_merge_processor.py
│       ├── field_analyzer.py   # Field naming with Gemini
│       └── executor.py         # docx-mailmerge2 execution
├── api/v3/endpoints/
│   └── mail_merge.py           # API endpoints
└── api/v3/api.py               # Add mail_merge_router
```

### Reusable Components in ai-server-xbot

- Authentication: `check_xgeni_tool_key` from `docx_form` endpoint
- Settings: `settings.GEMINI_API_KEY` from `core/config.py`
- Logger: Loguru from existing infrastructure
- File handling: Existing upload/download infrastructure

## API Endpoints (Demo)

```
POST /convert          # Upload .docx → Create mail merge template
POST /merge            # Template + Context → Final .docx
GET  /download/{id}    # Download result
```

## Running the Application

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## File Naming Conventions

- Use **kebab-case** for all file names (Python, JavaScript, etc.)
- Keep names descriptive and meaningful for LLM code analysis
- Example: `mail-merge-processor.py`, `context-form.jsx`

## Code Standards

- **Class-based architecture** for core logic (e.g., `SmartMailMergeConverter`)
- **Exception handling** for all file operations
- **No namespaces** in lxml xpath calls - use `w:` prefix directly
- **Comment placement**: Brief comments at Regex and XML manipulation logic

## Current Status

- ✅ Architecture design complete
- ✅ Technical requirements specified
- ⏳ Backend implementation pending
- ⏳ Frontend implementation pending
- ⏳ Integration with ai-server-xbot pending

## Key Implementation Constraints

1. **Greedy Matching**: Never create adjacent meaningless fields like `«field_1»«field_2»`
2. **Multi-line Placeholders**: Handle placeholders spanning multiple lines
3. **Fragmented Text**: DOCX text is split across multiple `w:r` tags - use offset mapping
4. **Checkbox Patterns**: Handle patterns like `□ Nghỉ không lương   □ Nghỉ bệnh    □ Khác: ...`
5. **Date Patterns**: Flexible handling of `ngày... tháng... năm 20...`

## Testing Priority

Test with Vietnamese forms containing:
- Multi-placeholder lines: "Tôi tên: ........ Số CMND: ........"
- Date fields: "[Hà Nội], ngày... tháng... năm 20..."
- Checkboxes: "□ Khác: .................."
- Multi-line placeholders spanning continued dot lines
