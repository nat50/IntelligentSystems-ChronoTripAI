# Figma ↔ API: các màn T1–T4 và D1–D4

Tài liệu này đối chiếu từng màn trong Figma "ChronoTrip AI – Product Design" với API backend, và mô tả các endpoint mới làm trong đợt này. Những trường do model M1–M3 trả về (best time, khoảng thời lượng, độ tin cậy, giờ mở cửa thật…) được mô tả ở [frontend-integration.md](frontend-integration.md); lý do thay đổi model ở [model-changes.md](model-changes.md).

Mọi endpoint mới đều **thêm vào**, không đổi endpoint cũ, nên frontend hiện tại vẫn chạy. Endpoint `/api/admin/*` vẫn cần header `X-Admin-Token` khi server đặt `CHRONOTRIP_ADMIN_TOKEN`.

## 1. Đối chiếu từng màn

✅ đã có API · ⚠️ có nhưng khác Figma (xem ghi chú) · ❌ chưa có

### Traveler

| Màn | Thành phần Figma | API | |
|---|---|---|---|
| T1 Trip setup | Destination (HCMC, Da Nang, Hanoi) | `GET /api/cities` (có Đà Nẵng) | ✅ |
| | Start date, Days, Day starts/ends, Stay | các trường của `OptimizeRequest`: `start_date`, `days`, `day_start`, `day_end`, `stay` | ✅ |
| | Pace Relaxed / Balanced / Packed | `preferences.pace` (0 / 0,5 / 1) | ✅ |
| | Interests (Food, Culture, Nature, Nightlife, Shopping) | `interest` trên mỗi place; `GET /api/places?interest=…` và `GET /api/places/suggest?interest=…` | ✅ |
| | Saved trips, Sign in | Saved trips: §3.4. **Không có đăng nhập** (đã chốt): nút "Sign in" / "My account" không có backend | ⚠️ |
| T2 Pick places | Danh sách theo độ phổ biến, tìm kiếm, chip lọc | `GET /api/places?q=…&interest=…` | ✅ |
| | Panel: Popularity (M1), Best time (M2), Typical visit length (M3), biểu đồ theo giờ, "Open 08:00–17:00 · Closed on Mondays", "Estimated by model version v1.2" | `GET /api/places/{id}`: `score`, `golden_*`, `duration*`, `conf_m1..3`, `hour_profile`, `open_min`/`close_min`/`closed_days`/`hours_source`, `model_versions` | ✅ |
| | Mark as must-visit | `OptimizeRequest.must_visit` | ✅ |
| | "Visit time of selected / Available" | frontend tự cộng `duration` và `(day_end − day_start) × days` | ✅ |
| T3 Itinerary | Lịch theo ngày, khoá giờ, re-optimize, Undo | `POST /api/itinerary/optimize` (`locks`, `seed_plan`) | ✅ |
| | "Building your itinerary… Generation 140 of 300 · best plan so far: 6 stops, 58 min travel", Cancel | `POST /api/itinerary/jobs`, poll `GET …/jobs/{id}`, `DELETE …/jobs/{id}` | ✅ |
| | "Not all must-visit places fit" + 3 cách sửa, Recommended | `ItineraryOut.plan_fit` | ✅ |
| | "Not scheduled · Theme park needs 4 h; the largest free gap is 2 h 10 min" | `unscheduled` + frontend tự tính khoảng trống lớn nhất từ `days[].stops` | ✅ |
| | "You moved Café to 11:15. Times below are estimated" | thuần frontend | ✅ |
| T4 Saved trips | Danh sách (Upcoming / Draft / Past), day overview | `POST /api/trips/lookup` → `status`, `overview` | ✅ |
| | Share with a link | `PUT /api/trips/{id}/share`, `GET /api/shared/{slug}` | ✅ |
| | Route file (.gpx) | `GET /api/trips/{id}/export.gpx`, `GET /api/shared/{slug}/export.gpx` | ✅ |
| | Calendar file (.ics) | `GET /api/trips/{id}/export.ics`, `GET /api/shared/{slug}/export.ics` | ✅ |
| | PDF itinerary | **không làm** ở backend; frontend có thể dùng chức năng in của trình duyệt (`window.print()` với CSS in, mỗi ngày một trang) | ❌ |
| | Help improve estimates | `improve_estimates` + `POST /api/trips/{id}/edits` | ✅ |

### Data scientist

| Màn | Thành phần Figma | API | |
|---|---|---|---|
| D1 Data | Thẻ Check-ins, Places, Cities ready, Last pipeline run | `GET /api/admin/data` | ✅ |
| | Sources (check-ins, place details crawl, OSRM) | `data.sources` (+ một dòng edit log từ T4) | ✅ |
| | Pipeline · last run (5 bước) | `data.pipeline` | ⚠️ các bước theo pipeline thật: Import → Clean visit lengths → Match opening hours → Build profiles → Publish |
| | Quality issues + nút hành động | `data.issues[].action`: `crawl_hours` → `POST /api/admin/hours/crawl`; `retrain` → `POST /api/admin/train`; `review_places` → mở D2 với `quality=low_data` | ✅ |
| | Run pipeline | `POST /api/admin/train` (đã có) | ✅ |
| | Add source | không có (nguồn dữ liệu cố định trong code) | ❌ |
| D2 Place explorer | Danh sách theo thành phố, tìm theo tên/ID, lọc All / Low data / Missing hours | `GET /api/admin/places?city&q&quality` | ✅ |
| | Check-ins, Unique users, % one-time, Opening hours, Data quality | `GET /api/places/{id}`: `n_checkins`, `n_users`, `one_time_share`, giờ mở cửa, `quality` | ✅ |
| | Biểu đồ check-in theo giờ và visit length, "Median 82 min · current M3 estimate 85 min" | `hour_profile`, `visit_hist` (+ `metrics.summary.visit_bin_edges`), `duration` | ✅ |
| | Bảng "Current model outputs" (version, confidence) | `model_versions`, `conf_m1..3` | ✅ |
| D3 Models | 3 thẻ model với trạng thái (Active v1.2 / Training 62% / New run ready) | `GET /api/admin/models` | ✅ |
| | Dataset, Split 80/10/10, Algorithm, Edit settings, Start training | `GET /api/admin/models/{m}` (`settings`, `split`); `POST /api/admin/models/{m}/train` | ⚠️ split chia **theo thời gian**, không chỉnh được |
| | Run #18: MAE, RMSE, Within ±15 min, learning curve, Largest errors | `versions[].metrics` (xem frontend-integration.md mục 5) | ✅ |
| | M3 versions: Activate / Active / Roll back | `versions[]`; `POST /api/admin/models/{m}/versions/{v}/activate` | ✅ |
| | "Before you activate: … +4 min per stop … 214 saved trips will be re-checked" | `GET /api/admin/models/{m}/versions/{v}/impact` | ⚠️ đếm được số chuyến bị ảnh hưởng nhưng **chưa tự kiểm tra lại** các chuyến đó |
| D4 Optimizer | Population, Generations, Crossover, Mutation, Time limit, Local search, Objective weights | `GET /api/admin/optimizer` | ✅ |
| | Run benchmark: Score change, Rule violations, Median run time, biểu đồ theo generation, bảng test case | `POST /api/admin/optimizer/benchmark`, poll `GET …/benchmarks/{id}` | ⚠️ test case giới hạn 30 địa điểm (luật hệ thống), không có "HCM · 60 places" |
| | Apply to planner | `POST /api/admin/optimizer/apply` | ✅ |

Số "Training · 62%" trên D3 chỉ là ước lượng thô: `progress` = 0 khi chờ, 0,5 khi đang train, 1 khi xong. LightGBM không báo phần trăm chính xác.

### Mức khớp

Trong 38 thành phần Figma ở hai bảng trên:
- **31 ✅** có API đúng như Figma.
- **5 ⚠️** có API nhưng khác Figma ở chi tiết:
  - không có đăng nhập (đã chốt);
  - các bước pipeline ở D1 đặt tên theo pipeline thật;
  - chia train/val/test theo thời gian, không chỉnh được;
  - "214 saved trips will be re-checked" mới đếm, chưa tự kiểm tra lại;
  - benchmark tối đa 30 địa điểm.
- **2 ❌** chưa có: xuất PDF (để frontend dùng chức năng in của trình duyệt) và "Add source" ở D1.

Như vậy API đã đủ để dựng **phần lớn** các màn Figma. Ba điều cần lưu ý:
1. Frontend đã gọi các API này (15/11/2026, §5): T1–T4 ở `/plan`, `/plan/places`, `/plan/itinerary`, `/plan/trips`, trang chia sẻ `/t/[slug]`; D1–D4 ở `/admin`, `/admin/places`, `/admin/models`, `/admin/optimizer`. Đăng nhập của Traveler là mock, chỉ lưu trong trình duyệt (`frontend/src/lib/account.ts`).
2. Mọi API mới đã chạy với frontend thật trên dữ liệu mẫu (`--sample`), chưa chạy trên dataset thật.
3. Các con số trên mockup (MAE 11.8 phút, "214 saved trips"…) là số minh hoạ; số thật phụ thuộc vào dữ liệu.

## 2. Thay đổi trên endpoint cũ (đều tương thích ngược)

| Endpoint | Thêm |
|---|---|
| `GET /api/cities` | Đà Nẵng (ward, chỗ ở mặc định "My An") |
| `GET /api/places` | query `interest` (lặp được: `?interest=food&interest=nature`), `q` (tên "Museum · An Khanh", phường, loại, tiền tố ID dataset hoặc id số) |
| `GET /api/places/suggest` | query `interest`; nhóm `food` luôn được giữ để có chỗ ăn |
| `Place` | `venue` (ID dataset, không đổi giữa các model version; D2 "ID"), `interest` (`food`/`culture`/`nature`/`nightlife`/`shopping`) |
| `PlaceDetail` | `model_versions` (`{"m1": "v3", "m2": "v3", "m3": "v5"}`), `quality` (`good`/`low_data`/`missing_hours`) |
| `OptimizeRequest` | `must_visit: number[]` (phải nằm trong `place_ids`) |
| `ItineraryOut` | `plan_fit` (null nếu mọi must-visit đều được xếp); `weights.golden_bonus` |
| `POST /api/itinerary/optimize` | dùng cấu hình optimizer đang active (D4) |

Nhóm sở thích suy từ nhãn địa điểm, theo đúng các ví dụ trong Figma: Market → Food, Night market → Nightlife, Theme park → Nature. Bảng đầy đủ: `INTEREST_OF_LABEL` trong `backend/ml/categories.py`.

`quality` của một địa điểm:
- `missing_hours`: không có giờ mở cửa thật **và** `confidence` (khung giờ ước lượng) không phải `high`.
- `low_data`: dưới 10 check-in.
- `good`: các trường hợp còn lại.

## 3. Endpoint mới cho Traveler

### 3.1 Must-visit và "No plan fits" (T2, T3)

Gửi `must_visit` trong request tối ưu. Địa điểm must-visit được cộng điểm rất lớn *bên trong solver* để luôn được ưu tiên xếp trước. `score` hiển thị và `fitness` trả về không bị ảnh hưởng. Nếu vẫn có must-visit không xếp được, response có:

```json
"plan_fit": {
  "missing": [44],
  "day": 0,
  "needed_min": 580,
  "available_min": 485,
  "fixes": [
    {"kind": "move_place", "label": "Move Theme park to Day 2", "patch": {"locks": [...]}, "fits": true, "recommended": true},
    {"kind": "extend_day", "label": "Extend Day 1 to end at 22:30", "patch": {"day_end": 1350}, "fits": true, "recommended": false},
    {"kind": "add_day", "label": "Add one more day", "patch": {"days": 3}, "fits": true, "recommended": false},
    {"kind": "drop_places", "label": "Remove 2 lower-rated stops", "patch": {"place_ids": [...]}, "fits": false, "recommended": false}
  ]
}
```

- `day`: ngày bị quá tải. Chỉ có giá trị khi mọi must-visit bị thiếu đều đã khoá vào cùng một ngày; nếu không thì là `null`, và `needed_min`/`available_min` tính cho cả chuyến.
- `patch`: các trường cần **thay** trong `OptimizeRequest`. Nút "Apply and re-optimize" = gộp `patch` vào request rồi gọi lại optimize.
- `fits`: backend đã thử tối ưu nhanh (~1 giây) với cách sửa đó và mọi must-visit đều được xếp.
- `recommended`: cách sửa ít xáo trộn nhất mà vẫn `fits`, theo thứ tự ưu tiên: dời địa điểm → kéo dài ngày → thêm ngày → bỏ bớt điểm dừng. Không cách nào `fits` thì không có `recommended`.
- Gợi ý kéo dài ngày tính cả giờ mở cửa muộn nhất của các địa điểm bị thiếu và một khoảng ăn trưa/tối.

Vì phải thử từng cách sửa, một request có `plan_fit` chậm hơn bình thường tối đa khoảng 4 giây.

### 3.2 Job tối ưu có tiến độ (T3 "Building your itinerary…")

| | |
|---|---|
| `POST /api/itinerary/jobs` | body giống `/optimize` → **202** `OptimizeJobOut` |
| `GET /api/itinerary/jobs/{id}` | trạng thái hiện tại (poll khoảng 300–500 ms) |
| `DELETE /api/itinerary/jobs/{id}` | yêu cầu huỷ; job chuyển sang `cancelled` sau generation đang chạy |

```json
{
  "id": "3f9c…", "status": "running",
  "generation": 140, "max_generations": 400,
  "best_stops": 6, "best_travel_min": 58,
  "steps": [
    {"key": "hours", "label": "Opening hours checked", "done": true},
    {"key": "travel", "label": "Travel times loaded", "done": true},
    {"key": "search", "label": "Searching for the best order", "done": false}
  ],
  "result": null, "error": null
}
```

- `status`: `running` → `done` (khi đó `result` là `ItineraryOut`), `failed` (`error`), hoặc `cancelled`.
- Solver thường dừng **trước** `max_generations` (khi không còn cải thiện hoặc hết thời gian), nên thanh tiến độ nên tính `generation / max_generations` nhưng nhảy lên 100% khi `status` là `done`.
- Job lưu trong bộ nhớ (tối đa 100 job) và mất khi server khởi động lại.

### 3.3 Saved trips (T4), không có tài khoản

Mỗi chuyến đi có một **edit token** bí mật, chỉ trả về **một lần** khi tạo. Frontend lưu danh sách `{id, token}` trong `localStorage`; xoá storage là mất quyền sửa các chuyến đó. Gửi token qua header `X-Trip-Token`, hoặc qua `?token=` cho link tải file. Sai token hay id không tồn tại đều trả cùng một **404**.

| Method | Path | Body → Response |
|---|---|---|
| POST | `/api/trips` | `{title?, request: OptimizeRequest, itinerary?: ItineraryOut, improve_estimates?: bool}` → **201** `TripOut` + `edit_token` |
| POST | `/api/trips/lookup` | `{trips: [{id, token}, …]}` → `TripOut[]`, sắp theo ngày bắt đầu (chuyến chưa có ngày xếp cuối); cặp sai bị bỏ qua |
| GET | `/api/trips/{id}` | → `TripOut` |
| PATCH | `/api/trips/{id}` | `{title?, request?, itinerary?, improve_estimates?}` → `TripOut` (gửi `"itinerary": null` để xoá lịch) |
| DELETE | `/api/trips/{id}` | → 204 |
| PUT | `/api/trips/{id}/share` | `{enabled: bool}` → `TripOut` với `share_slug` |
| GET | `/api/shared/{slug}` | (không cần token) → `SharedTripOut` (chỉ đọc, không có token hay request) |
| GET | `/api/trips/{id}/export.gpx` · `/api/shared/{slug}/export.gpx` | file `application/gpx+xml` |
| GET | `/api/trips/{id}/export.ics` · `/api/shared/{slug}/export.ics` | file `text/calendar` |
| POST | `/api/trips/{id}/edits` | `{events: [{kind, place_id?, day?, value?}]}` → `{stored}` |

`TripOut`:

| Trường | Ý nghĩa |
|---|---|
| `status` | `draft` (chưa có lịch hoặc chưa có ngày), `upcoming`, `past` (ngày cuối đã qua) |
| `start_date`, `end_date`, `days`, `stops` | cho thẻ chuyến đi ("14–16 Nov 2026 · 3 days · 17 stops") |
| `overview[]` | `{day, date, stops, travel_minutes, first_stop, back_at}`: bảng "day overview" |
| `request` | request đã lưu, **với id địa điểm của model version đang active** (backend tự đổi id qua `venue`) |
| `stale_places` | id địa điểm mà version hiện tại không còn; báo người dùng chọn lại |
| `share_enabled`, `share_slug` | link chia sẻ là `<origin>/t/{share_slug}` (frontend tự dựng URL); slug dạng `hcm-3d-a1b2c3` |
| `improve_estimates` | công tắc "Help improve estimates" |

Link chia sẻ: tắt rồi bật lại thì vẫn giữ **cùng slug**.

Edit log (`kind`: `move`, `remove`, `add`, `lock`, `unlock`, `set_duration`, `reoptimize`; `value` là giờ bắt đầu mới hoặc thời lượng mới, tính bằng phút):
- Chỉ được lưu khi `improve_estimates` đang bật; nếu không, API trả `stored: 0` và không ghi gì.
- Bản ghi lưu **không có** id chuyến đi: chỉ có thành phố, `venue`, nhãn, loại thao tác, giá trị, thời lượng M3 đã dự đoán và model version.
- Gợi ý: gửi khi người dùng lưu chuyến đi, không cần gửi từng thao tác.

File `.gpx`: mỗi điểm dừng là một `<wpt>` (tên "Day 1 · 2. Museum · An Khanh"; có `<time>` theo giờ +07:00 khi chuyến có ngày), mỗi ngày là một `<rte>` đi từ chỗ ở qua các điểm dừng rồi về chỗ ở. Chuyến chưa có lịch trả **409**.

File `.ics` (RFC 5545), dùng cho "Adds each stop as an event":
- Mỗi điểm dừng là một `VEVENT`, từ giờ bắt đầu tới giờ rời đi theo lịch, múi giờ `Asia/Ho_Chi_Minh` (UTC+7, có khai báo `VTIMEZONE`).
- `SUMMARY` là "Museum · An Khanh"; có `LOCATION`, `GEO` và ghi chú thời lượng ước lượng. Điểm dừng đã đặt giờ (khoá giờ) có thêm "Booked time".
- `UID` ổn định theo chuyến, ngày và điểm dừng, nên nhập lại file sẽ cập nhật sự kiện thay vì tạo trùng.
- Cần cả lịch và ngày bắt đầu: thiếu một trong hai trả **409**. Lịch không có ngày thì không đặt được sự kiện vào lịch.

## 4. Endpoint mới cho Data console

### 4.1 D1 · Data

`GET /api/admin/data` → `DataOverview`:

| Trường | Figma |
|---|---|
| `checkins`, `checkins_period` | thẻ "Check-ins 18.24 M · Apr 2012 – Jan 2014" |
| `places` | thẻ "Places (POIs)": số địa điểm của version đang active |
| `cities[]` `{name, places, ready}` | thẻ "Cities ready 3 of N". `ready` khi có ≥ 50 địa điểm |
| `last_run`, `last_run_minutes`, `dataset_version` | thẻ "Last pipeline run · Completed in 42 min" |
| `sources[]` `{key, name, provides, rows, updated, status}` | bảng Sources. `status`: `imported`, `synced`, `outdated` (crawl quá 30 ngày), `missing`, `online` (đã cấu hình OSRM), `estimate` (không có OSRM) |
| `pipeline[]` `{key, label, value}` | khối "Pipeline · last run" |
| `issues[]` `{key, impact, title, detail, action}` | "Quality issues", đã sắp theo `impact` (high → low) |

Crawl lại giờ mở cửa: `POST /api/admin/hours/crawl` → 202, rồi poll `GET /api/admin/hours` → `{running, places, usable, updated, error}`. Giờ mới chỉ có hiệu lực sau khi **train lại** (`POST /api/admin/train`), vì bước ghép giờ nằm trong pipeline.

### 4.2 D2 · Place explorer

`GET /api/admin/places?city=…&q=…&quality=good|low_data|missing_hours&limit=100&offset=0` → `{city, total, places: [{id, venue, name, group, n_checkins, quality}]}`, sắp theo số check-in giảm dần. `total` là tổng số địa điểm của thành phố, dùng cho dòng "9,812 places". Chi tiết một địa điểm dùng `GET /api/places/{id}` như T2. "Open in traveler view" chỉ cần mở T2 với cùng `id`.

### 4.3 D3 · Models

Mỗi model giờ có **version riêng**. Một model version (`v3`, `v5`…) gồm cả ba model; mỗi model trong đó ghi nhớ version nào đã thực sự train nó. Train lại M3 tạo version mới chỉ có M3 mới, M1 và M2 được chép từ version đang active.

| Method | Path | |
|---|---|---|
| GET | `/api/admin/models` | 3 `ModelCard` |
| GET | `/api/admin/models/{m}` | `ModelDetail` = card + `versions[]` (các lần train model đó, mới nhất trước) |
| POST | `/api/admin/models/{m}/train` | `{settings}` → 202 `JobOut` (poll `GET /api/admin/jobs/{id}`). **Không** tự kích hoạt |
| GET | `/api/admin/models/{m}/versions/{v}/impact` | `ImpactOut`: hộp "Before you activate" |
| POST | `/api/admin/models/{m}/versions/{v}/activate` | 202 `JobOut`; dùng cho cả Activate và Roll back |

`ModelCard`: `{key, name, description, active_version, status, progress, latest, settings, split}`.
- `active_version`: version đã train model đang dùng (ví dụ M3 "Active v5").
- `status`: `active`, `training` (kèm `progress`), `new_run_ready` (có lần train mới hơn chưa kích hoạt), `failed`, `untrained`.
- `settings`: giá trị hiện tại cho "Edit settings".
- `split`: `{kind: "time", train_end, val_end, shares: {train, val, test}}`, tỉ lệ check-in rơi vào mỗi phần.

Tham số cho phép (khác danh sách này thì trả 422):

| Model | Tham số (mặc định, khoảng) |
|---|---|
| m1 | `learning_rate` (0,05; 0,005–0,5), `num_leaves` (63; 7–255), `n_cutoffs` (5; 1–8) |
| m2 | `quiet_floor` (0,4; 0–0,9), `window_mass` (0,9; 0,5–0,99) |
| m3 | `learning_rate` (0,05; 0,005–0,5), `num_leaves` (31; 7–255) |

`versions[]`: `{version, created_at, source, trained, origin, active, headline, metrics, settings}`. `headline` = `{name, value, baseline, unit, higher_is_better}` (M1 Spearman, M2 log-likelihood, M3 MAE phút), dùng cho dòng "Run #18 · MAE 11.8 min".

Activate: backend tạo version mới gồm version đang active với model đó thay bằng bản lấy từ `v`, chạy lại suy luận cho mọi địa điểm, rồi kích hoạt. Nếu đã có sẵn version chứa đúng tổ hợp đó (thường gặp khi rollback) thì chỉ kích hoạt, và job trả về `status: "done"` ngay. Kích hoạt đúng tổ hợp đang dùng trả 409.

`ImpactOut`: `{places_compared, places_changed, mean_change, unit, trips_affected, message}`. So sánh trên bảng thuộc tính của `v` với bảng đang active, theo cột `score` (M1, thay đổi ≥ 5 điểm), `golden_start` (M2, ≥ 60 phút) hoặc `duration` (M3, ≥ 5 phút). `trips_affected` = số chuyến đã lưu có ít nhất một địa điểm thay đổi. Backend **chưa** tự kiểm tra lại các chuyến đó.

### 4.4 D4 · Optimizer

| Method | Path | |
|---|---|---|
| GET | `/api/admin/optimizer` | `{active: OptimizerSettings, updated_at, last_benchmark}` |
| POST | `/api/admin/optimizer/benchmark` | `OptimizerSettings` → 202 `BenchmarkOut` (`status: running`) |
| GET | `/api/admin/optimizer/benchmarks/{id}` | `BenchmarkOut` |
| POST | `/api/admin/optimizer/apply` | `OptimizerSettings` → `OptimizerOut`. Mọi lần tối ưu sau đó dùng cấu hình này |

`OptimizerSettings`: `population` (100), `generations` (400), `crossover` (0,85), `mutation` (0,15), `time_limit_s` (6), `local_search` (true), `objective` `{popularity: 0.6, golden: 0.3, travel: 0.1}` (tổng phải bằng 1, nếu không trả 422). Giá trị mặc định cho kết quả giống hệt trước khi có màn D4. `time_limit_s` luôn bị giới hạn bởi `CHRONOTRIP_SOLVER_TIME_LIMIT_S` của server.

Ý nghĩa của objective: mỗi trọng số nhân thêm một phần của hàm mục tiêu, so với giá trị mặc định. `popularity` → w1 (tổng điểm); `golden` → phần thưởng golden hour (Beta − 1, mặc định 0,25); `travel` → w2 và w3 (thời gian di chuyển và chờ).

`BenchmarkOut`: `{status, settings, active, score_change, violations, median_runtime_s, curve, cases[], ready_to_apply, error}`.
- `cases[]`: `{name, city, places, days, score_active, score_new, violations, runtime_s}`, mỗi case chạy 3 lần và lấy trung vị.
- `curve`: `{generation[], active[], new[]}` cho case đầu tiên.
- `ready_to_apply`: điểm không giảm, không vi phạm luật, và thời gian chạy trong giới hạn.
- Một benchmark mất khoảng 4 case × 2 cấu hình × 3 lần × thời gian giới hạn (khoảng 1–2 phút với mặc định). Mỗi lúc chỉ chạy được một benchmark (409 nếu đang chạy).

## 5. Việc phía frontend cho các màn mới

1. `src/lib/types.ts`: thêm kiểu cho `PlanFit`, `PlanFix`, `OptimizeJob`, `Trip`, `SharedTrip`, `DataOverview`, `ExplorerPage`, `ModelCard`/`ModelDetail`/`Impact`, `OptimizerSettings`/`Benchmark`. Các tên trường khớp với `backend/app/schemas.py`.
2. T1: chip Interests → `interest`; thêm Đà Nẵng (danh sách lấy từ `/api/cities`).
3. T2: ô tìm kiếm → `q`; nút must-visit → `must_visit`; dòng "Estimated by model version …" → `model_versions`.
4. T3: chuyển sang `POST /api/itinerary/jobs` + poll để có hộp "Building your itinerary…"; hộp "Not all must-visit places fit" từ `plan_fit`.
5. T4: trang Saved trips mới; lưu `{id, token}` vào localStorage; route `/t/[slug]` cho trang chia sẻ chỉ đọc; nút tải `.gpx` và `.ics` (dùng link `?token=` để trình duyệt tải thẳng); nút PDF dùng chức năng in của trình duyệt; gửi edit log khi lưu chuyến (nếu người dùng bật).
6. D1–D4: bốn tab mới của Data console, theo §4. Màn `/admin/models` hiện tại có thể thay bằng D3.

## 6. Thay đổi trong code (đợt này)

| File | Thay đổi |
|---|---|
| `backend/solver/schedule.py`, `memetic.py`, `report.py`, `problem.py` | Phần thưởng golden hour thành tham số (`Weights.golden`, mặc định 0,25 như cũ); `Objective` cho D4; callback `on_generation` để báo tiến độ / huỷ; `GAConfig.local_search` |
| `backend/ml/geo.py`, `sample.py` | Đà Nẵng: 12 phường, chỗ ở mặc định; dữ liệu mẫu có Đà Nẵng |
| `backend/ml/categories.py` | `INTEREST_OF_LABEL`, `interest_of`, `labels_of_interest` |
| `backend/ml/models.py` | `SETTINGS` + `check_settings`; tham số của M1/M2/M3 thành trường của class; M2 lưu `quiet_floor`, `window_mass` |
| `backend/ml/pipeline.py` | `train_all(models=…, base=…, settings=…)` train một phần; `compose()` ghép model từ nhiều version; meta có `components`, `trained`, `settings`; `processed_dir`, `read_meta` |
| `backend/ml/preprocess.py` | `quality.json` có thêm `split_counts`, `split_dates` |
| `backend/app/orm.py` | Bảng `trips`, `edit_logs`, `optimizer_configs`, `benchmarks`; `ModelVersion.components/trained/settings`; `TrainingJob.kind/target` (đều có `server_default`, DB cũ được tự thêm cột) |
| `backend/app/schemas.py` | Kiểu cho mọi endpoint ở trên |
| `backend/app/services/planner.py` | must-visit, `plan_fit`, tiến độ / huỷ, cấu hình optimizer |
| `backend/app/services/optimizer.py` (mới) | cấu hình D4, benchmark, job tối ưu trong bộ nhớ |
| `backend/app/services/training.py` | job `model` (train một model) và `compose` (kích hoạt / rollback) |
| `backend/app/services/console.py` (mới) | D1 overview, crawl giờ mở cửa, D2 explorer, D3 cards / impact |
| `backend/app/services/quality.py` (mới) | nhãn chất lượng và bộ lọc tìm kiếm dùng chung |
| `backend/app/services/versions.py` | lưu và đọc `components`, `trained`, `settings` |
| `backend/app/routers/trips.py` (mới) | T4: chuyến đi đã lưu, chia sẻ, xuất `.gpx` và `.ics`, edit log |
| `backend/app/routers/itinerary.py`, `places.py`, `admin.py`, `main.py` | các endpoint mới |
| `backend/tests/test_api.py` | 7 test mới cho T1–T4 và D1–D4 (gồm cả xuất `.gpx` và `.ics`) |

Kết quả: `cd backend && ../.venv/Scripts/python -m pytest -q` → **51 passed**.
