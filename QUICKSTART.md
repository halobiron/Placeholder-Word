# Quick Start Guide - Mail Merge Placeholder System

## 🚀 Setup lần đầu

### 1. Backend setup

```bash
cd backend

# Chạy setup script (tạo venv + install dependencies)
./setup.sh

# Thêm Gemini API Key
nano .env
# GEMINI_API_KEY=AIzaSy...  <-- Paste API key của bạn vào đây

# Start backend
./start.sh
```

### 2. Frontend setup

Mở terminal mới:

```bash
cd frontend

# Install dependencies
npm install

# Start frontend
npm run dev
```

### 3. Open browser

http://localhost:5173

## 🔑 Lấy Gemini API Key

1. Vào: https://aistudio.google.com/app/apikey
2. Đăng nhập Google account
3. Click "Create API Key"
4. Copy key → paste vào `backend/.env`

## 📝 Cách dùng

1. **Upload**: Kéo file .docx vào
2. **Xem fields**: Hệ thống tự detect
3. **Nhập data**: Điền thông tin
4. **Download**: Nhận file kết quả

## ⚡ Quick commands

```bash
# Backend
cd backend && ./start.sh

# Frontend  
cd frontend && npm run dev

# Setup lại (nếu cần)
cd backend && ./setup.sh
```

## 🐛 Lỗi?

```bash
# Check backend health
curl http://localhost:8000/health

# Re-install dependencies
cd backend && ./setup.sh

# Check logs
# Terminal đang chạy backend sẽ show logs
```

## 📁 Files quan trọng

- `backend/.env` - API keys
- `backend/venv/` - Virtual environment
- `backend/main.py` - API endpoints
- `frontend/src/App.jsx` - Main UI

## 🔄 Re-start

```bash
# Dùng lại lần sau
cd backend && ./start.sh      # Backend
cd frontend && npm run dev    # Frontend
```

Không cần chạy `setup.sh` nữa!
