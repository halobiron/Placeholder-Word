# Story: Backend Setup & FastAPI Configuration

**ID:** story-backend-setup
**Epic:** Phase 1 - Backend Core
**Priority:** P0 (Blocker)
**Status:** pending

## Overview
Initialize FastAPI backend application with basic configuration, CORS, and project structure.

## User Story
**As** Developer
**I want** setup FastAPI backend
**So that** can start implementing mail merge features

## Acceptance Criteria
- [ ] FastAPI app running on port 8000
- [ ] CORS middleware configured
- [ ] Directory structure created
- [ ] Requirements.txt with all dependencies
- [ ] Upload/Download directories created
- [ ] Health check endpoint working

## Dependencies
- None

## Technical Details

### Directory Structure
```
backend/
├── main.py
├── requirements.txt
└── uploads/
    ├── templates/
    └── results/
```

### Dependencies
```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-multipart==0.0.6
python-docx==1.1.0
lxml==4.9.3
docx-mailmerge2==1.0.1
google-generativeai==0.3.2
python-dotenv==1.0.0
```

### Endpoints
```python
GET /health    # Health check
```

## Definition of Done
- [ ] Code implemented
- [ ] Can run `uvicorn main:app --reload`
- [ ] Health check returns 200 OK
- [ ] No linting errors
