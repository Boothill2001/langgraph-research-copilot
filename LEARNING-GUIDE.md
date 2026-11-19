# Research Copilot — học từ dữ liệu đến báo cáo

Đây là hướng dẫn học tiếng Việt. README và hình ảnh portfolio dùng tiếng Anh.

## Chuẩn bị

Bấm `start.bat`, mở Workspace, giữ chế độ **Learn**. Đăng nhập `researcher`, mật khẩu demo `learn-local-only` (có thể đổi bằng biến môi trường `COPILOT_DEMO_PASSWORD`). Đây là danh tính local để học, chưa phải SSO doanh nghiệp.

Tạo request mặc định: tìm RRF, tính `1/(60+1) + 1/(60+3)`, lưu báo cáo. Đừng bấm Run ngay: thử đoán output trước mỗi lần bấm Execute next node.

## 1. Data trước khi model xuất hiện

Mở **Data → index**. Chọn trang RRF. Đọc URL, hash, ngày tải và số chunk. Mỗi chunk là một đoạn văn có metadata và quyền truy cập. Embedding là vector số dùng để tìm đoạn gần nghĩa; nó không phải câu trả lời.

Tự trả lời: Khi một tài liệu thay đổi, vì sao phải tạo snapshot/index mới thay vì giữ nguyên hash? Thông tin nào là dữ liệu chính thức và thông tin nào là fixture giả lập?

## 2. Understand: câu chữ → yêu cầu có cấu trúc

Bấm node đầu. So sánh request với `spec`: query, nguồn cần tìm, biểu thức cần tính và có cần báo cáo hay không. Model tách yêu cầu; backend vẫn kiểm tra schema. Không có trường nào cho model tự cấp role.

Giữ **Follow latest execution / Theo kết quả mới nhất** bật để output tự chuyển theo mỗi lần chạy. Các nút 01–07 chỉ mở lịch sử của node; chúng không chạy node đó. Khi bạn xem bước cũ, UI sẽ báo đang xem lịch sử. Bấm **Execute next node** sẽ tự quay về kết quả mới nhất.

Tự trả lời: Nếu yêu cầu “tính giúp phần trăm” nhưng không có số, hệ thống nên hỏi gì? Việc hiểu intent sai ảnh hưởng các node sau ra sao?

## 3. Planner: chọn bước tiếp theo

Planner dùng tool calling để đề xuất bước tiếp theo. Backend chỉ thực hiện một hành động hợp lệ mỗi lần; các đề xuất khác không tự chạy. Xem `proposed_calls` nếu provider đề xuất nhiều lời gọi dù parallel bị tắt.

Tự trả lời: Vì sao cần lấy bằng chứng trước khi viết báo cáo? Planner có thể tự duyệt bản nháp không?

## 4. Tools: MCP → RAG service riêng

Node tools gửi arguments theo schema qua MCP stdio. Token danh tính được runtime truyền bằng context tin cậy, không nằm trong arguments do model tạo.

Mở trace: dense và BM25 tìm trên các chunk đã lọc quyền; RRF cộng `1/(60+rank)` từ mỗi danh sách; reranker đọc cặp câu hỏi–đoạn văn; gate chặn evidence yếu. Điểm reranker không phải xác suất đúng.

Tự tính một số hạng của chunk đứng hạng 1 ở dense và hạng 3 ở BM25. Đối chiếu với calculator. Xem sự khác nhau giữa “tìm đúng tài liệu trong top 5” và “trả lời chính xác nội dung”.

## 5. Calculator và Draft

Calculator dùng AST có giới hạn, không dùng Python eval. Đối chiếu biểu thức đầu vào với giá trị trả về. Draft phải có nguồn đã truy xuất; danh sách citation chỉ được tham chiếu chunk đã cấp phép. Kiểm tra citation tồn tại chưa chứng minh toàn bộ câu văn được nguồn hỗ trợ: vẫn cần đọc đối chiếu.

Tự trả lời: LLM có cần tự tính toán khi đã có calculator không? Tại sao kết quả calculator được đính vào bản báo cáo cần duyệt?

## 6. Approval: dừng thật, không chỉ nhắc trong prompt

Tiếp tục đến `awaiting_approval`. Đọc toàn bộ draft và hash. Thử duyệt bằng researcher: backend sẽ không cho phép. Chuyển sidebar sang `reviewer`, đăng nhập lại, mở đúng run và duyệt/từ chối.

Thử lần nữa bằng một run mới: khi đang chờ duyệt, researcher sửa draft. Hash thay đổi và approval cũ không còn hợp lệ. Reviewer phải đọc đúng bản mới.

## 7. Save và phục hồi

Sau khi duyệt, báo cáo chuẩn được ghi vào SQLite với action ID duy nhất; Markdown là bản xuất có thể tạo lại. Bấm tải file. Gửi cùng thao tác nhiều lần không được tạo thêm report ID.

Restart agent khi đang chờ approval rồi mở lại run: checkpoint nằm trên đĩa, không mất theo process. Kiểm thử lỗi giữa commit và export bằng `python -m pytest tests/test_copilot.py -k crash -v`; test không gọi API và không tạo số liệu model giả.

## 8. Hiểu experiment trước khi kể trong phỏng vấn

So sánh ba orchestrator trên cùng task, model, tool và quyền. Workflow cố định có thể rẻ hơn với chuỗi bước đã biết. LangGraph có checkpoint và ranh giới thực thi rõ, nhưng không tự làm câu trả lời đúng hơn.

Retrieval report chấm đúng nguồn theo tài liệu, chưa phải annotation độ liên quan ở cấp chunk hay đánh giá faithfulness đầy đủ. Task suite nhỏ do tác giả biên soạn; không đại diện chất lượng production. Approval trong benchmark là fixture, approval khi bạn thao tác trên UI là quyết định thật của tài khoản reviewer.

Ghi câu trả lời, output quan sát được và điều còn chưa hiểu vào `LEARNING-JOURNAL.txt`. Khi phỏng vấn, kể bối cảnh → quyết định → ca lỗi → cách kiểm thử → giới hạn. Không nhận đây là triển khai tại công ty cũ.
