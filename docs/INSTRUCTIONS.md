# Replacing blank to placeholder prompt
Role: Senior Python Developer & MS Word OOXML Architect.
Task: Viết một script Python bằng thư viện python-docx và lxml để chuyển đổi các biểu mẫu tiếng Việt định dạng .docx (chứa các đoạn dấu chấm/gạch dưới để trống) thành template Microsoft Word Mail Merge chuẩn (sử dụng thẻ <w:fldSimple>).
Context & Challenges (Đặc điểm Input):

Biểu mẫu tiếng Việt thường dùng dấu ..., ___, hoặc … (ellipsis) để tạo không gian điền.
Một dòng có thể chứa nhiều cụm placeholder (VD: Tôi tên: ........ Số CMND: ........). Hoặc các trường hợp có ký tự đặc biệt xen giữa như: □ Nghỉ không lương   □ Nghỉ bệnh    □ Khác: .................
Một placeholder có thể kéo dài nhiều dòng (dòng tiếp theo chỉ toàn dấu chấm).
Có các dòng ngày tháng xen kẽ (VD: [Địa danh], ngày... tháng... năm 20...).
Văn bản trong file .docx bị phân mảnh (fragmented) thành nhiều thẻ <w:r> (Run) khác nhau, làm gãy Regex thông thường.
Strict Technical Constraints & Logic Requirements:
1. Kỹ thuật "XML Surgical Injection" & "Offset Mapping" (Bắt buộc):

KHÔNG sử dụng API cấp cao paragraph.add_run() hoặc paragraph.text.replace().
Phải duyệt qua từng paragraph, lập bản đồ (Offset Mapping) độ dài và vị trí của các Run gốc (w:r) để lưu lại thuộc tính định dạng w:rPr (Bold, Italic, Size...).
Xóa các Run gốc và xây dựng lại toàn bộ XML của paragraph đó.
Khi tạo thẻ Mail Merge <w:fldSimple w:instr=" MERGEFIELD {tên_biến} \* MERGEFORMAT ">, nó phải được bọc trong một <w:r> kế thừa chính xác w:rPr tại đúng vị trí ký tự của dấu chấm gốc.
2. Hợp nhất Placeholder (Greedy Matching):

Sử dụng Regex quét toàn bộ cụm dấu chấm (kể cả khi chúng bị ngắt quãng bởi khoảng trắng/Tab): ([._…]{2,}(?:\s+[._…]{2,})*).
Tuyệt đối không tạo ra 2 field liền kề nhau vô nghĩa như «field_1»«field_2».
3. Đặt tên Field thông minh (Smart Labeling) & Context Memory:
Ưu tiên 1 - Nhãn liền kề (Inline Context - Bắt buộc kiểm tra đầu tiên): Quét ngược chuỗi TextSegment ngay sát trước cụm dấu chấm. Ưu tiên lấy cụm từ ngay trước dấu hai chấm (:). Nếu không có, lấy cụm trước dấu gạch (-). Nếu không có, lấy tối đa 3-4 từ gần nhất (VD: Lý do: ... -> ly_do, Đang học lớp: ... -> dang_hoc_lop). Chỉ khi Inline Context hoàn toàn trống hoặc không có ý nghĩa thì mới chuyển sang các ưu tiên dưới.
Ưu tiên 2 - Xử lý Thời gian & Năm học (Time Context): Nếu Inline Context liền trước là ngày, tháng, năm thì đặt tên field tương ứng. Đặc biệt, nếu gặp pattern Năm học: 20... - 20..., phải gom hoặc xử lý khéo léo thành biến nam_hoc hoặc nam_bat_dau, nam_ket_thuc thay vì lấy nhãn là 20.
Ưu tiên 3 - Kế thừa phân cấp (Section-Based Context): Khi duyệt qua các tiêu đề mục lớn (VD: 1. Về con chung:), hãy lưu lại tên mục. NHƯNG CHỈ SỬ DỤNG nhãn mục lớn này khi dòng hiện tại là một gạch đầu dòng/checkbox CHỈ chứa placeholder (không có text) hoặc là dòng nối tiếp chỉ toàn dấu chấm.
Lọc nhiễu văn bản (Noise Reduction): Sử dụng Regex để tự động loại bỏ các cụm từ hướng dẫn dư thừa (VD: (nếu có), (ghi rõ...)) ra khỏi văn bản trước khi lấy nhãn, không đưa chúng vào tên Field.
Slugify & De-duplication: Chuyển tiếng Việt có dấu thành không dấu, lowercase, format snake_case. Cắt bỏ tối đa giữ lại 3-4 từ có nghĩa. Tự động thêm hậu tố _2, _3 nếu trùng tên biến.

4. Khái quát hóa bằng Tokenization (Xử lý Text xen kẽ & Ngày tháng linh hoạt):

KHÔNG hard-code Regex để bóc tách/thay thế cứng nhắc toàn bộ dòng ngày tháng. Thay vào đó, áp dụng phương pháp phân mảnh (Tokenize): Cắt toàn bộ text của Paragraph thành mảng các "Segment" đan xen nhau gồm TextSegment (chữ thuần túy, checkbox, tiền tố 'năm 20') và FieldSegment (vị trí của chuỗi dấu chấm).
Khi gán nhãn cho một FieldSegment, hãy nhìn ngược vào TextSegment liền trước nó:
Nếu đoạn text liền trước khớp pattern (?i)(ngày|tháng|năm)\s*(20)?\s*$, hãy đặt tên field tương ứng là ngay, thang, nam.
Nếu là các text khác (VD: □ Khác: ), xử lý theo Rule 3 ở trên.
Mục đích: Phương pháp này đảm bảo giữ nguyên tuyệt đối các đoạn TextSegment (không làm mất cụm " năm 20", không làm vỡ ký tự "□") và chỉ bơm cấu trúc <w:fldSimple> thẳng vào các vị trí FieldSegment, giải quyết triệt để và an toàn mọi format đứt đoạn từ ngày...tháng...năm... cho đến □ Khác:..........
Output Requirement:

Cung cấp toàn bộ mã nguồn Python class-based (VD: class SmartMailMergeConverter:), hoàn chỉnh, không cắt bớt, có handle exception cơ bản. Kèm theo comment giải thích ngắn gọn tại các logic Regex và XML Manipulation.
Tuyệt đối không dùng namespaces=... trong các hàm .xpath() của đối tượng OXML (_p, _r). Chỉ sử dụng prefix w: trực tiếp.

# Replacing placeholder to provided context prompt

Use `pip install docx-mailmerge2==1.0.1` to replace the placeholders as follows:
Hôm nay, ngày 31/03/2026 tại Hà Nội, tôi là Nguyễn Văn A (Mã nhân viên: EMP001), hiện đang đảm nhiệm vị trí Developer thuộc phòng IT của công ty ABC Corp, xin thông báo về việc nghỉ phép của mình. Vì lý do cá nhân, tôi xin phép được nghỉ theo chế độ nghỉ phép năm trong vòng 3 ngày, cụ thể từ ngày 01/04/2026 đến hết ngày 03/04/2026. Trong thời gian này, tôi đã thực hiện bàn giao lại toàn bộ công việc cho ông/bà Trần Văn B hiện là Team Lead để đảm bảo tiến độ của bộ phận. Mọi vấn đề cần liên lạc gấp, quý công ty có thể phản hồi qua số điện thoại 0123456789 hoặc email a@example.com.
