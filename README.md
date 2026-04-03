# Mail Merge Placeholder System

Demo web application chuyển đổi file Word có vùng trống (dấu chấm, gạch dưới) thành Microsoft Word Mail Merge templates, sau đó điền dữ liệu bằng AI.

## 🎯 Tính năng

- ✅ Tự động phát hiện placeholders (dấu chấm, gạch dưới)
- ✅ Đặt tên field thông minh với Gemini AI (hỗ trợ tiếng Việt)
- ✅ Xử lý multi-line placeholders
- ✅ Tự động điền dữ liệu từ context
- ✅ Download file .docx kết quả

## 🏗️ Kiến trúc

```
Frontend (React + Vite)
    ↓ HTTP
Backend (FastAPI)
    ↓
Mail Merge Processor
    ↓
Gemini AI (Smart field naming)
```

## 📋 Yêu cầu

- Python 3.10+
- Node.js 18+
- Gemini API Key

## 🚀 Cài đặt

### 1. Clone repository

```bash
git clone <repository-url>
cd placeholder
```

### 2. Backend Setup

```bash
cd backend

# Tạo file .env từ .env.example
cp .env.example .env

# Thêm Gemini API Key vào .env
# GEMINI_API_KEY=your_actual_api_key_here

# Cài đặt dependencies
pip install -r requirements.txt

# Chạy backend (port 8000)
./start.sh
# Hoặc: uvicorn main:app --reload --port 8000
```

### 3. Frontend Setup

Mở terminal mới:

```bash
cd frontend

# Cài đặt dependencies
npm install

# Chạy frontend (port 5173)
./start.sh
# Hoặc: npm run dev
```

### 4. Truy cập ứng dụng

Mở browser: http://localhost:5173

## 📖 Cách sử dụng

1. **Upload file**: Kéo thả file .docx vào vùng upload
2. **Xem fields**: Hệ thống tự động phát hiện và đặt tên fields
3. **Nhập dữ liệu**: Điền thông tin vào form
4. **Tải xuống**: Nhận file .docx đã điền dữ liệu

## 🧪 Testing

### Test với file mẫu

Tạo file .docx với nội dung:

```
Tôi tên: ....................................................
Số CMND: ....................

Ngày ... tháng ... năm 20 ...

Địa chỉ: ...........................................................
.....................................................................

□ Nghỉ không lương   □ Nghỉ bệnh    □ Khác: .....................
```

## 🔧 Cấu hình

### Backend (.env)

```bash
GEMINI_API_KEY=your_gemini_api_key_here
MAX_FILE_SIZE=10485760
```

### Frontend (.env)

```bash
VITE_API_BASE=http://localhost:8000
```

## 📁 Cấu trúc dự án

```
placeholder/
├── backend/
│   ├── main.py                    # FastAPI app
│   ├── mail_merge_processor.py    # Core logic
│   ├── gemini_client.py           # Gemini integration
│   ├── merge_executor.py          # Mail merge execution
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── FileUpload.jsx
│   │   │   ├── ContextForm.jsx
│   │   │   └── DownloadBtn.jsx
│   │   ├── App.jsx
│   │   └── api.js
│   └── package.json
├── docs/
│   ├── ARCHITECTURE.md
│   └── INSTRUCTIONS.md
└── README.md
```

## 🚀 Tích hợp vào ai-server-xbot

Sau khi demo thành công, port code:

```
ai-server-xbot/modules/
├── utils/
│   └── mail_merge/
│       ├── processor.py
│       ├── field_analyzer.py
│       └── executor.py
├── api/v3/endpoints/
│   └── mail_merge.py
└── api/v3/api.py
```

## 🐛 Troubleshooting

### Backend không start được

```bash
# Kiểm tra Python version
python3 --version  # Cần 3.10+

# Cài lại dependencies
pip install -r requirements.txt

# Kiểm tra Gemini API Key
cat .env
```

### Frontend không upload được

```bash
# Kiểm tra backend đang chạy
curl http://localhost:8000/health

# Kiểm tra CORS configuration
# Xem backend/main.py
```

### Gemini API lỗi

```bash
# Test API key
curl https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=YOUR_API_KEY

# Kiểm tra quota
# https://aistudio.google.com/app/apikey
```

## 📝 License

Demo project - Internal use only

## 🤝 Contributing

Pull requests are welcome!

## 📧 Support

For issues and questions, please create an issue in the repository.
