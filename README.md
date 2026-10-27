# Tín hiệu đầu tư – chạy tự động trên GitHub

Gói này thay cho 3 tác vụ định kỳ trên Claude. GitHub tự chạy các bộ quét theo lịch, đăng dashboard thành một trang web, rồi gửi thông báo qua Telegram. Bạn không cần Claude, và máy tính của bạn cũng không cần bật.

| Bộ quét | Khi nào chạy | Dữ liệu |
|---|---|---|
| Ichimoku 3D & tuần | Mỗi sáng khoảng 7:15 | Binance |
| Tín hiệu V2 khung tuần | Sáng thứ Hai | Binance + DNSE |
| Mua đáy và giữ | Sáng thứ Hai | Binance + CoinMarketCap + DNSE |

GitHub đôi khi chạy trễ lịch từ 5 đến 30 phút, đó là chuyện bình thường.

---

## Cài đặt (làm một lần, khoảng 15 phút)

### 1. Tạo tài khoản và kho chứa trên GitHub
1. Vào https://github.com/signup và tạo tài khoản miễn phí.
2. Bấm dấu **+** ở góc trên bên phải, chọn **New repository**.
3. Ở ô **Repository name**, gõ `tin-hieu-dau-tu`. Chọn **Public**, rồi bấm **Create repository**.
   > Kho phải để Public thì GitHub Pages mới miễn phí. Như vậy ai có đường link đều xem được dashboard và mã. Trong đó chỉ có dữ liệu giá công khai, không có thông tin cá nhân. Mã Telegram được cất riêng trong mục bí mật, người khác không xem được.

### 2. Tải các tệp lên
1. Giải nén file `tin-hieu-dau-tu.zip` ra máy.
2. Trong trang kho vừa tạo, bấm **uploading an existing file**, hoặc chọn **Add file → Upload files**.
3. Mở thư mục đã giải nén, chọn **toàn bộ nội dung bên trong**: `.github`, `docs`, `scripts`, `README.md`, `requirements.txt`, `.gitignore`. Kéo tất cả vào trang GitHub, rồi bấm **Commit changes**.
   > **Trên Mac**, các thư mục bắt đầu bằng dấu chấm bị ẩn. Nhấn **Cmd + Shift + .** trong Finder để hiện thư mục `.github`.
   > Kiểm tra lại sau khi tải: trong kho phải thấy thư mục `.github/workflows/update.yml`. Nếu không thấy, xem mục **Xử lý sự cố** ở cuối.

### 3. Bật trang dashboard
1. Trong kho, vào **Settings → Pages**.
2. Ở mục **Source**, chọn **GitHub Actions**.

### 4. Tạo bot Telegram để nhận thông báo
1. Trong Telegram, tìm **@BotFather** và gửi lệnh `/newbot`.
2. Đặt tên cho bot. BotFather sẽ trả về một **token** dạng `123456789:ABC...`. Hãy chép lại.
3. Tìm bot vừa tạo và bấm **Start**, hoặc gửi cho nó một tin bất kỳ.
4. Mở trình duyệt, vào địa chỉ sau (thay `<TOKEN>` bằng token của bạn):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Tìm đoạn `"chat":{"id":123456789` và chép con số đó. Đây là **chat id**.

### 5. Lưu token vào GitHub
Vào **Settings → Secrets and variables → Actions → New repository secret**, rồi tạo 2 mục:

| Name | Secret |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token ở bước 4.2 |
| `TELEGRAM_CHAT_ID` | chat id ở bước 4.4 |

### 6. Chạy thử lần đầu
1. Vào tab **Actions**. Nếu GitHub hỏi, bấm **I understand my workflows, go ahead and enable them**.
2. Ở cột trái, chọn **Cập nhật tín hiệu**, rồi bấm **Run workflow**. Ở ô "Chạy bộ nào", chọn **all**, rồi bấm **Run workflow**.
3. Chờ khoảng 5–7 phút cho đến khi hiện dấu ✅. Telegram sẽ nhận 3 tin nhắn.
4. Dashboard nằm ở `https://<tên-tài-khoản>.github.io/tin-hieu-dau-tu/`. Link cũng có trong cuối mỗi tin Telegram và trong **Settings → Pages**. Bạn nên lưu link này lên màn hình chính của điện thoại.

Từ đây mọi thứ chạy tự động.

---

## Dùng hằng ngày
- **Thông báo Telegram** là bản tóm tắt: MUA MỚI, THOÁT, CHỜ LẦN 3…
- **Dashboard** có đủ chi tiết: tab Tổng quan, Ichimoku 3D, Ichimoku tuần, V2 tuần, Mua đáy. Bạn có thể lọc theo crypto hoặc chứng khoán, lọc theo trạng thái, tìm mã, bấm tiêu đề cột để sắp xếp, và xem lịch sử lệnh.
- **Chạy tay bất cứ lúc nào:** vào Actions → Cập nhật tín hiệu → Run workflow. Chọn `all` để chạy cả 3 bộ, hoặc chọn `ichi`, `v2`, `bh` để chạy riêng từng bộ.
- Nếu một bộ quét bị lỗi, ví dụ nguồn giá tạm ngừng, Telegram sẽ báo ⚠️ và dashboard giữ nguyên dữ liệu cũ.

## Thay đổi danh sách mã
Mở file trong thư mục `scripts/` trên GitHub, bấm biểu tượng bút chì để sửa, rồi bấm **Commit changes**:
- `build_ichi.py`: sửa `COINS_3D` và `COINS_1W`
- `v2scan.py`: sửa `C_WATCH`, `V_WATCH`, `VN30`
- `bhscan.py`: sửa `CRYPTO`, `STOCKS`

## Đổi giờ chạy
Sửa dòng `cron` trong `.github/workflows/update.yml`. Giờ ghi trong đó là giờ UTC, tức giờ Việt Nam trừ 7. Ví dụ `"13 0 * * *"` nghĩa là 07:13 sáng giờ VN. V2 và Mua đáy luôn tự chạy kèm vào lần chạy của sáng thứ Hai.

## Xử lý sự cố
- **Không thấy tab "Cập nhật tín hiệu" trong Actions:** thư mục `.github` chưa được tải lên. Bấm **Add file → Create new file**, gõ tên `.github/workflows/update.yml`, dán nội dung của file đó (mở bằng Notepad hoặc TextEdit) vào, rồi bấm **Commit changes**.
- **Không nhận được tin Telegram:** kiểm tra lại 2 secret ở bước 5, và chắc chắn bạn đã bấm Start với bot.
- **Phần chứng khoán báo lỗi:** máy chủ GitHub đặt ở nước ngoài, nên nguồn DNSE đôi khi có thể từ chối truy cập. Thông báo ⚠️ sẽ nêu lý do. Crypto vẫn chạy bình thường.
- **Lịch tự tắt:** GitHub tắt lịch chạy của kho không có thay đổi nào trong 60 ngày. Vì bộ quét lưu dữ liệu mới mỗi ngày, chuyện này thường không xảy ra. Nếu có, vào Actions và bấm **Enable workflow**.

---
Chỉ là công cụ theo dõi, không phải khuyến nghị đầu tư.
