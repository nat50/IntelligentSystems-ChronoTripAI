# Thay đổi M1–M3 theo thiết kế Figma

Ngày: 14/11/2026. Phạm vi: chỉ backend (`backend/ml`, `backend/app`), **chưa sửa `frontend/`**. Những gì frontend cần làm để dùng các thay đổi này nằm ở [frontend-integration.md](frontend-integration.md).

## Vì sao đổi

So thiết kế Figma (luồng T1–T4 cho Traveler, D1–D4 cho Data Scientist) với code lúc đó, có năm chỗ lệch nằm ở model:

| # | Figma | Code trước khi sửa | Đã làm |
|---|---|---|---|
| 1 | Giờ mở cửa lấy từ web crawl ("Open 08:00–17:00 · Closed on Mondays") | M2 tự đoán giờ mở cửa = khung giờ chứa 90% check-in | Lấy giờ thật từ OpenStreetMap; ước lượng chỉ dùng khi không có giờ thật |
| 2 | "Best time" = đang mở cửa và vắng hơn giờ cao điểm | `golden_window` chọn 120 phút **đông nhất** | Viết lại thành `best_starts` |
| 3 | D3 đo M3 bằng MAE, RMSE, Within ±15 min, có learning curve và "Largest errors" | Chỉ có pinball loss | Thêm đủ các metric đó |
| 4 | Độ tin cậy riêng cho từng model (D2: M1 High, M2 High, M3 Medium) | Một nhãn chung, theo ngưỡng số check-in 30/10 | `conf_m1`, `conf_m2`, `conf_m3` |
| 5 | D1: "Vietnam has only 48,357 check-ins → Use regional priors" | Thu hẹp (shrink) về loại địa điểm và thành phố, nhưng hầu hết địa điểm ở VN vẫn bị gắn `low` | Thêm prior theo phường cho M2; feature theo khu vực cho M1 và M3 |

Hai quyết định đã chốt với nhóm:
- Best time đi theo Figma, thay cho cách cũ "densest 120 min".
- Các số trên mockup (MAE 11.8 phút, Within ±15 min 78%) chỉ là số minh hoạ. Nhãn thời lượng được suy ra từ khoảng cách giữa hai lần check-in liên tiếp nên nhiễu nhiều, và kết quả trên dữ liệu thật sẽ kém hơn các số đó.

## Thay đổi theo file

### `backend/ml/models.py`

**M1 · Popularity (`M1Popularity`)**
- *Trước:* một cặp duy nhất: feature tính đến hết tập train, target là số người dùng trong 2 tháng tập val.
- *Sau:* nhiều mốc cắt nối tiếp nhau (rolling origin): 5 mốc cách nhau 2 tháng, mốc cuối là `TRAIN_END`. Ở mỗi mốc, feature dùng dữ liệu trước mốc, target là số người dùng trong 2 tháng sau mốc. Một địa điểm luôn nằm cùng một phía train/holdout ở mọi mốc, để tránh rò rỉ dữ liệu. Không target nào dùng tới giai đoạn test. Số dòng train tăng từ 1.484 lên 7.420 trên dữ liệu mẫu.
- *Feature mới:* `users_recent_pm` (3 tháng gần nhất), `one_time_share`, và ba feature **không phụ thuộc vào lịch sử của chính địa điểm**, dành cho địa điểm ít dữ liệu: `nbr_users_500m`, `nbr_users_2km` (trung bình của các địa điểm khác trong cùng ô lưới) và `area_users` (trung bình của các địa điểm cùng loại, cùng phường).
- *Metric mới:* `ndcg20` (chất lượng top 20 theo từng thành phố), `by_city`, `by_bucket`, `n_cutoffs`.
- Điểm `score` (1–100) vẫn tính như cũ: hạng phần trăm của độ phổ biến dự đoán trong cùng thành phố.

**M2 · Hour profile (`M2HourProfile`)**
- *Prior phân cấp:* loại → thành phố → **phường** → địa điểm. Tầng phường mới có tham số `kappa_ward`, chọn trên tập validation từ {5, 20, 80, 1e9}; giá trị 1e9 tương đương tắt tầng này, nên model tự bỏ tầng phường khi nó không giúp ích. `_fit_priors` được viết lại bằng `groupby`.
- *Khung giờ ước lượng (`hour_windows`, dạng vector hoá):* khung giờ giờ đây nằm trong một "ngày kinh doanh" từ 04:00 đến 04:00 hôm sau. Trước đây, một công viên đông vào sáng sớm và chiều tối có thể nhận khung "16:00–09:00" vắt qua đêm. Bây giờ nó nhận "05:00–19:00", còn bar vẫn có thể mở tới sau nửa đêm.
- *Best time (`best_starts`, thay cho `golden_window`):*
  - `food`, `nightlife`: 120 phút đông nhất. Giờ vắng của quán ăn hay quán bar không phải lúc nên đến.
  - Các nhóm khác: 120 phút vắng nhất **kết thúc trước giờ cao điểm**. Khung này phải nằm trong giờ mở cửa, còn đủ một lượt tham quan trước giờ đóng, và vẫn đạt ít nhất `QUIET_FLOOR` = 40% mức đông của giờ cao điểm (để không chọn những giờ "chết" sát lúc mở/đóng cửa). Nếu trước giờ cao điểm không có khung nào hợp lệ thì lấy khung vắng nhất trong ngày.
  - `golden_window` vẫn được giữ cho code cũ còn gọi tới (trả về khung đông nhất).
- *Độ tin cậy (`stability`):* lấy 30 mẫu từ phân phối hậu nghiệm Dirichlet, rồi tính lại best time và khung giờ trên từng mẫu. Độ tin cậy là tỉ lệ mẫu cho kết quả lệch không quá 1 giờ so với ước lượng: từ 80% trở lên là `high`, từ 50% là `medium`, còn lại là `low`. Cách này thay ngưỡng đếm cứng 30/10 check-in: địa điểm ít check-in nhưng thuộc loại có giờ giấc ổn định sẽ không còn bị gắn `low` oan.
- *Metric mới:* `by_city`, `by_bucket`, `kappa_ward`, và `hours_eval` (sai số giữa giờ mở/đóng ước lượng và giờ thật, được ghi trong pipeline).
- Đọc được `m2.npz` cũ (không có bảng phường).

**M3 · Visit length (`M3VisitLength`)**
- *Ba mô hình phân vị:* q25, q50, q75 (`lower`, `booster`, `upper`). `duration` = q50; `duration_lo` và `duration_hi` = q25 và q75. Ba giá trị được sắp lại cho đúng thứ tự.
- *Feature mới:* `venue_dwell` (thời lượng điển hình của địa điểm, thu hẹp về mức của loại × thành phố, rồi về mức của loại, với hệ số 5 lượt ảo); `log_visits`; `effort`; `density_500m`. Dòng train dùng encoding **out-of-fold** (5 fold) để mỗi dòng không nhìn thấy chính nhãn của nó. Val dùng encoding tính từ train; test dùng encoding tính từ train+val.
- *Metric theo D3:* `mae`, `rmse`, `within_15` tính theo từng địa điểm (trung vị thời lượng đo được trong giai đoạn test so với trung vị dự đoán). Chỉ tính địa điểm có ≥ 3 lượt; nếu không đủ 20 địa điểm như vậy thì hạ ngưỡng xuống 1. Có thêm `learning_curve` (pinball của train/valid theo từng vòng, tối đa ~80 điểm), `largest_errors` (top 5 ở thành phố đang phục vụ), `coverage_50`, `by_city`, `by_bucket`.
- `predict_venues` đổi chữ ký: `(venues, visits, idx, hour) → mảng (n, 3)`.
- Đọc được model cũ chỉ có `m3.txt`.

### `backend/ml/preprocess.py`
- `build_visits` không còn cắt cứng ở 360 phút. Hàm mới `trim_visits` cắt theo phân vị 97,5% của từng loại địa điểm (loại có dưới 200 lượt thì dùng phân vị chung), và không bao giờ vượt `MAX_DWELL_MIN` = 360. Lý do: khoảng cách tới lần check-in kế tiếp còn chứa cả những chỗ người dùng ghé mà không check-in, nên phần đuôi phải bị nhiễu.
- Ghép giờ mở cửa thật (`hours.prepare`) → `processed/hours.parquet`. File này bị xoá ở mỗi lần chạy, để không dùng lại kết quả ghép cũ.
- Ghi `processed/quality.json`: số lượt bị loại, số địa điểm khớp được giờ thật (cho D1 "Quality issues").

### `backend/ml/hours.py` (mới)
- `python -m ml.hours --raw data/raw`: tải mọi địa điểm OSM có thẻ `opening_hours` trong bán kính 30 km quanh TP.HCM và Hà Nội qua Overpass API (thử lần lượt 3 máy chủ, mỗi máy tối đa 3 vòng), rồi lưu vào `data/raw/osm_hours.json`. Pipeline chỉ đọc file này, nên vẫn chạy offline; không có file thì mọi giờ mở cửa đều là ước lượng như trước.
- `parse_opening_hours` đọc phần thông dụng của cú pháp OSM: danh sách ngày, khoảng giờ, `off`, `24/7`, giờ qua nửa đêm, nghỉ trưa (lấy từ giờ mở sớm nhất tới giờ đóng muộn nhất), tên ngày dạng 3 chữ, `PH`, và nhiều quy tắc ngăn bằng dấu phẩy. Khi các ngày có giờ khác nhau thì lấy khung giờ xuất hiện nhiều nhất. Chuỗi ngoài phạm vi này (tháng, sunrise, "by appointment"…) bị bỏ qua.
- `match`: mỗi địa điểm được ghép với địa điểm OSM **cùng nhóm** gần nhất trong vòng 100 m (theo quy tắc ở bước 3 màn D1).
- Lần crawl thật ngày 14/11/2026: lấy về 4.030 địa điểm OSM; 2.725 địa điểm có giờ đọc được và thuộc nhóm ứng viên. Phần bị loại chủ yếu là ATM, cửa hàng tiện lợi, ngân hàng, khách sạn… (không phải địa điểm tham quan), và 80 chuỗi giờ ghi tự do.

### `backend/ml/pipeline.py`
- `batch_infer(venues, checkins, visits, m1, m2, m3, opening)` trả về `(bảng thuộc tính, thông tin)`. Thứ tự tính: hồ sơ giờ (M2) → thời lượng (M3, tại giờ đông nhất) → khung giờ ước lượng (giờ đóng = giờ đến cuối + một lượt, tối đa 2 giờ) → thay bằng giờ thật nếu có → best time → độ tin cậy → điểm (M1).
- Cột mới trong `attributes.parquet`: `duration_lo`, `duration_hi`, `closed_days`, `hours_source`, `conf_m1`, `conf_m2`, `conf_m3`, `n_visits`, `one_time_share`, `visit_hist` (danh sách đủ cột nằm trong `ATTRIBUTE_COLUMNS`).
- `confidence` (cột cũ) nghĩa là "khung giờ mở cửa có đáng tin không": `high` nếu là giờ thật, nếu không thì theo độ ổn định của khung giờ ước lượng. `services/planner.py` vẫn dùng nó để làm mềm khung giờ, nên không phải sửa solver.
- `conf_m1`: theo số người dùng (≥ 20 là `high`, ≥ 5 là `medium`). `conf_m3`: ≥ 20 lượt đo được là `high`; ≥ 5 lượt, hoặc là loại địa điểm đã biết và có khoảng q25–q75 hẹp (≤ 60% của trung vị), là `medium`.
- `metrics.summary`: `visit_bin_edges`, `data_quality`, số địa điểm theo từng mức tin cậy của mỗi model và mỗi thành phố, và `hours_source`. Được lưu trong `metrics` vì API trả trường này cho từng version.
- Đã bỏ hàm `confidence()` (ngưỡng 30/10).

### `backend/ml/sample.py`
- Sinh thêm `osm_hours.json` giả theo đúng định dạng thật: khoảng 45% địa điểm ở hai thành phố có giờ mở cửa, tuỳ theo loại (ví dụ bảo tàng nghỉ Thứ Hai, công viên giải trí nghỉ Thứ Ba). Các số này dùng bộ sinh số ngẫu nhiên riêng, nên dữ liệu check-in giữ nguyên như trước.

### `backend/app`
- `orm.Place`: 10 cột mới, cột nào cũng có `server_default`.
- `db.init_db` → `_add_missing_columns`: tự `ALTER TABLE … ADD COLUMN` cho cột có `server_default` mà bảng chưa có. Nhờ vậy DB SQLite/PostgreSQL tạo bởi bản cũ vẫn dùng được, không cần xoá. Dòng cũ nhận giá trị mặc định (ví dụ `conf_m3 = "low"`) cho tới khi train version mới.
- `services/versions.register_version`: version train bằng code cũ (thiếu cột mới) vẫn nạp được, với `duration_lo = duration_hi = duration` và `conf_m* = confidence`.
- `schemas`: `PlaceOut` và `PlaceDetail` có thêm trường; `OptimizeRequest.start_date`; `ItineraryOut.warnings`.
- `services/planner.optimize`: xử lý ngày nghỉ khi có `start_date`. Không động tới `solver/`: địa điểm rơi vào ngày nghỉ được chuyển sang ngày mở cửa, khoá (`lock_day`) vào đó, rồi giải lại một lần. Chi tiết hành vi ở [frontend-integration.md](frontend-integration.md#4-lập-lịch-t1--trip-setup-t3--itinerary).
- `routers/itinerary`: lỗi `ValueError` từ planner trả về 422.
- `routers/places.suggest`: ưu tiên `confidence == "high"`, không đủ mới lấy thêm mức thấp hơn. Trước đây hàm này chỉ lấy `high`; vì `confidence` đã đổi nghĩa nên giữ bộ lọc cứng thì có thể không còn đủ địa điểm để gợi ý.

### Test
- `tests/test_ml.py` (mới, 22 test): parser giờ OSM, ánh xạ loại OSM sang nhóm, khung giờ không vắt qua đêm, best time (vắng với điểm tham quan, đông với quán ăn, kết thúc trước giờ đóng), NDCG.
- `tests/test_api.py`: thêm 3 test: thuộc tính địa điểm (khoảng thời lượng, best time nằm trong giờ mở cửa, giờ thật, histogram); metric cho màn D3; tránh ngày nghỉ (dời sang ngày khác, đưa vào `unscheduled`, trả 422, cảnh báo khi đã lock).
- Kết quả: `cd backend && ../.venv/Scripts/python -m pytest -q` → **44 passed**.

## Kết quả

### Dữ liệu mẫu (synthetic, `--sample`)

So pipeline cũ (commit `f4aea41`) với pipeline mới trên cùng bộ dữ liệu mẫu (seed 42):

| Metric | Cũ | Mới | Baseline |
|---|---|---|---|
| M1 Spearman, toàn bộ | 0.869 | **0.887** | 0.890 (số lượt/tháng) |
| M1 Spearman, Việt Nam | 0.821 | **0.853** | 0.856 |
| M1 NDCG@20 (trung bình 2 thành phố) | – | 0.992 | 0.992 |
| M2 log-likelihood | −2.610 | −2.610 | −2.635 (theo loại) |
| M3 pinball (phút) | 9.24 | 8.22 | 9.42 → 8.52 |
| M3 MAE / RMSE theo địa điểm (phút) | – | **7.99 / 11.19** | 9.03 / 12.62 |
| M3 Within ±15 min | – | **87%** | 80% |
| M3 độ phủ khoảng q25–q75 | – | 50,2% (kỳ vọng 50%) | |

Cách đọc bảng:
- **M1** tốt hơn rõ so với M1 cũ, nhất là ở Việt Nam, nhưng vẫn **chưa vượt baseline** đếm số lượt. Trên dữ liệu mẫu đây là điều dễ hiểu: độ phổ biến của mỗi địa điểm được sinh cố định nên số lượt quá khứ gần như là lời giải tối ưu. Cần dữ liệu thật để kết luận.
- **M2:** log-likelihood không đổi, vì trên dữ liệu mẫu tầng phường tự tắt (`kappa_ward = 1e9`): dữ liệu mẫu chỉ khác nhau theo loại địa điểm, không theo phường. Thay đổi chính của M2 nằm ở cách *dùng* hồ sơ giờ (best time, khung giờ, độ tin cậy), không nằm ở chính hồ sơ.
- **M3:** pinball của bản cũ và bản mới tính trên hai tập nhãn hơi khác nhau, vì `trim_visits` cắt nhãn theo cách mới. Vì vậy hãy so mỗi bản với baseline của chính nó: bản cũ tốt hơn baseline 1,9%, bản mới tốt hơn 3,5%.
- **Độ tin cậy ở hai thành phố** (`metrics.summary.confidence`): với M2, TP.HCM có 296 high / 52 medium / 49 low; trước đây cột `confidence` cũ chỉ dựa trên số check-in.
- `hours_eval` trên dữ liệu mẫu (giờ mở lệch 104 phút, giờ đóng lệch 137 phút) **không có ý nghĩa**: giờ mở cửa giả trong mẫu được đặt độc lập với hồ sơ check-in. Chỉ số này chỉ đáng xem trên dữ liệu thật.

Ví dụ best time trên dữ liệu mẫu: bảo tàng 08:00–10:00 (mở 08:00, đông nhất 14:00); trung tâm thương mại 11:00–13:00; nhà hàng 18:00–20:00; bar 21:00–23:00. Ở 648 địa điểm, không có best time nào nằm ngoài giờ mở cửa.

### Dữ liệu thật (LBSN2Vec++)

**Chưa chạy.** Bộ dữ liệu 2,68 GB tải về với tốc độ khoảng 0,1 MB/s (ước tính ~10 giờ). Lệnh tải đang chạy và tải tiếp được từ chỗ đã dừng:

```bash
cd backend
../.venv/Scripts/python -m ml.download --dest data/raw      # tải (hoặc tải tiếp)
../.venv/Scripts/python -m app.bootstrap --skip-download    # train + kích hoạt; dùng osm_hours.json nếu có
```

Sau khi train, cần điền vào đây: các metric ở trên tính cho Việt Nam và theo nhóm số check-in (`by_bucket`); tỉ lệ high/medium/low của từng model ở TP.HCM và Hà Nội; `hours_eval`. Theo kế hoạch: bước nào không thắng baseline trên dữ liệu Việt Nam thì quay lại cách cũ.

## Vấn đề còn mở
- M2 ở nhóm 0–9 check-in (dữ liệu mẫu): log-likelihood −2.659, **kém** baseline theo loại (−2.631). `kappa_venue` được chọn chung cho mọi địa điểm, nên có thể cần một `kappa` riêng cho địa điểm ít dữ liệu. Mẫu ở nhóm này mới có 197 check-in, cần xem lại trên dữ liệu thật.
- `QUIET_FLOOR` (0,4) và các ngưỡng tin cậy (0,8 / 0,5, 20 / 5 người dùng, 20 / 5 lượt) được chọn bằng tay trên dữ liệu mẫu.
- Giờ mở cửa OSM không ghi ngày lễ (`PH`) và chỉ giữ một khung giờ mỗi ngày. Ngày có giờ khác thường (ví dụ Chủ Nhật đóng sớm) dùng khung giờ phổ biến nhất trong tuần.
- Chưa làm (ngoài phạm vi lần này): version riêng cho từng model như D3 (hiện một version gồm cả ba model); dùng edit log từ T4 làm nhãn cho M3; Đà Nẵng; màn D4.
