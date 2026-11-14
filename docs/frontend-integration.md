# Nối frontend với model M1–M3 mới

Tài liệu này mô tả những gì backend trả thêm sau khi làm lại M1–M3 theo Figma "ChronoTrip AI – Product Design", và frontend cần sửa gì để dùng. Lý do và chi tiết thuật toán nằm ở [model-changes.md](model-changes.md). Bảng đối chiếu **từng màn Figma** (T1–T4, D1–D4) với API, cùng các endpoint mới (chuyến đi đã lưu, job tối ưu, must-visit, Data console), nằm ở [figma-api.md](figma-api.md).

**Frontend hiện tại vẫn chạy được mà không cần sửa gì.** Không trường nào bị xoá hay đổi tên, mọi trường mới đều có giá trị mặc định. Tuy vậy có **hai trường cũ đổi nghĩa** (mục 1), nên một vài nhãn trên giao diện cũ sẽ nói sai cho tới khi được sửa.

## 1. Trường cũ đổi nghĩa

| Trường | Trước | Bây giờ | Việc ở frontend |
|---|---|---|---|
| `golden_start`, `golden_end` | 120 phút **đông nhất** theo check-in | **Giờ nên đến** (Figma T2: "best time (open, fewer crowds)"). Với `group` là `food` hoặc `nightlife`: vẫn là 120 phút đông nhất (giờ ăn, giờ quán đông). Với các nhóm còn lại: 120 phút vắng nhất **trước giờ cao điểm**, nằm trọn trong giờ mở cửa, đủ thời gian cho một lượt tham quan trước giờ đóng, và vẫn có ít nhất 40% mức đông của giờ cao điểm (tránh mấy giờ "chết" sát lúc mở/đóng cửa). | Đổi nhãn "golden hour" thành "Best time". Sửa câu mô tả "golden hour = densest 120 min" trong `src/features/admin/AdminScreens.tsx`. |
| `open_min`, `close_min` | Luôn là ước lượng: khung giờ chứa 90% check-in | Nếu `hours_source == "crawl"` thì là **giờ mở cửa thật** lấy từ OpenStreetMap. Nếu `"estimated"` thì vẫn là ước lượng từ check-in, nhưng giờ đóng đã cộng thêm một lượt tham quan (check-in ghi giờ *đến*, không phải giờ về). | Bỏ chữ "(from check-ins)" cố định trong `src/components/map/MapView.tsx`, hiển thị theo `hours_source`. |
| `confidence` | Theo số check-in: ≥ 30 high, 10–29 medium, < 10 low | Độ tin cậy **của khung giờ mở cửa**: `high` nếu là giờ thật (crawl), nếu không thì tính theo độ ổn định của khung giờ ước lượng (xem `conf_m2` bên dưới). Planner vẫn dùng trường này như cũ: `low` thì khung giờ được coi là "mềm". | Có thể giữ nguyên. Nếu muốn hiển thị độ tin cậy theo từng model như Figma D2/T2 thì dùng `conf_m1..3`. |

Hệ quả nhỏ: `GET /api/places/suggest` trước đây chỉ lấy địa điểm `confidence == "high"`. Giờ nó lấy `high` trước, chỉ khi không đủ mới bù thêm `medium`/`low`.

## 2. `Place` (T2 · Pick places, T3 · Itinerary)

Áp dụng cho `GET /api/places`, `GET /api/places/suggest` và `place` trong mỗi stop của `POST /api/itinerary/optimize`.

| Trường mới | Kiểu | Mặc định | Ý nghĩa | Hiển thị theo Figma |
|---|---|---|---|---|
| `duration_lo` | `number` (phút) | = `duration` | Phân vị 25% thời lượng tham quan (M3) | T2: "≈ 85 min" dùng `duration`; khoảng "65–105 min" dùng `duration_lo`–`duration_hi` |
| `duration_hi` | `number` (phút) | = `duration` | Phân vị 75% thời lượng tham quan | |
| `hours_source` | `"crawl" \| "estimated"` | `"estimated"` | Nguồn của `open_min`/`close_min` | `"crawl"`: "Open 08:00–17:00". `"estimated"`: thêm nhãn "Estimated" |
| `closed_days` | `number[]` | `[]` | Thứ đóng cửa trong tuần, **0 = Thứ Hai … 6 = Chủ Nhật** (giống Python `weekday()`, **khác** JS `Date.getDay()` vốn lấy 0 = Chủ Nhật). Chỉ có khi `hours_source == "crawl"`. | T2: "Closed on Mondays" |
| `conf_m1` | `Confidence` | `"low"` | Độ tin cậy của điểm phổ biến (`score`) | T2 thẻ "Popularity · Model M1"; D2 cột Confidence |
| `conf_m2` | `Confidence` | `"low"` | Độ tin cậy của giờ nên đến (`golden_*`) | T2 thẻ "Best time to visit · Model M2" |
| `conf_m3` | `Confidence` | `"low"` | Độ tin cậy của thời lượng (`duration`) | T2 thẻ "Typical visit length · Model M3" |

Đổi phút sang giờ như cũ (`src/lib/time.ts`). `close_min` có thể lớn hơn 1440 khi địa điểm đóng cửa sau nửa đêm (ví dụ bar 17:00–02:00 là `1020`–`1560`).

Ví dụ thật (dữ liệu mẫu):

```json
{
  "id": 110, "city": "Ho Chi Minh City", "ward": "Phuoc Long B", "lat": 10.819923, "lon": 106.780215,
  "category": "Museum", "label": "Museum", "group": "sightseeing", "effort": 2, "score": 77,
  "duration": 85, "open_min": 480, "close_min": 1020, "golden_start": 480, "golden_end": 600,
  "confidence": "high", "n_checkins": 54, "estimated": true,
  "duration_lo": 65, "duration_hi": 105, "hours_source": "crawl", "closed_days": [0],
  "conf_m1": "high", "conf_m2": "high", "conf_m3": "high"
}
```

## 3. `PlaceDetail` (`GET /api/places/{id}`, T2 panel bên phải và D2 · Place explorer)

Gồm mọi trường của `Place`, `hour_profile` như cũ, và thêm:

| Trường mới | Kiểu | Ý nghĩa | Figma |
|---|---|---|---|
| `n_users` | `number` | Số người dùng khác nhau đã check-in | D2 "Unique users 1,402" |
| `one_time_share` | `number` 0–1 | Tỉ lệ người chỉ check-in đúng một lần | D2 "61% one-time visitors" |
| `n_visits` | `number` | Số lượt có đo được thời lượng (đầu vào của M3) | D2 "Visit length", ghi chú dưới biểu đồ |
| `visit_hist` | `number[]` (13 phần tử) | Số lượt theo từng khoảng 20 phút: `[0–20, 20–40, …, 220–240, 240+]`. Mốc dưới của mỗi khoảng nằm trong `metrics.summary.visit_bin_edges` (mục 5). | D2 biểu đồ "Visit length"; tô cột chứa `duration` |

`hour_profile` (24 số, tổng bằng 1, theo giờ địa phương) vẫn dùng cho biểu đồ "Check-ins by hour". Ở T2/D2, cột được tô màu là các giờ từ `golden_start` tới `golden_end`.

## 4. Lập lịch (T1 · Trip setup, T3 · Itinerary)

### Request `POST /api/itinerary/optimize`

| Trường mới | Kiểu | Mặc định | Ý nghĩa |
|---|---|---|---|
| `start_date` | `string` `"YYYY-MM-DD"` | `null` | Ngày đầu chuyến đi (T1 "Start date"). Có trường này thì planner mới biết mỗi ngày của chuyến là thứ mấy để tránh `closed_days`. Không gửi thì mọi thứ chạy như trước. |

### Response

| Trường mới | Kiểu | Ý nghĩa |
|---|---|---|
| `warnings` (ở cấp itinerary) | `string[]` | Cảnh báo cho cả chuyến, khác với `days[i].warnings`. Ví dụ: `"Museum · Phuoc Long B is closed on every day of this trip"`, `"Museum · Phuoc Long B is closed on Monday; it was planned on a day it is open"`. |

Cách planner xử lý ngày nghỉ:
- Địa điểm đóng cửa **mọi ngày** của chuyến bị đưa thẳng vào `unscheduled`, kèm một cảnh báo ở `warnings`.
- Địa điểm đóng cửa **một vài ngày** thì được dời sang ngày nó mở cửa.
- Địa điểm người dùng đã **lock** vào một ngày đóng cửa thì vẫn giữ nguyên, kèm cảnh báo `"… is usually closed on this day"` trong `days[i].warnings`.
- Nếu mọi địa điểm đã chọn đều đóng cửa trong những ngày đi, API trả **422** với `detail` là `"Every selected place is closed on the days of this trip"`.

T3 · state "No plan fits" có thể dựa vào `unscheduled` và `warnings` để gợi ý cách sửa.

## 5. Màn hình quản trị (D1 · Data, D3 · Models)

`GET /api/admin/overview` → `versions[i].metrics` vẫn có `m1`, `m2`, `m3` với các khoá cũ, và thêm các khoá mới bên dưới. Bảng metric hiện tại trong `AdminScreens.tsx` vẫn chạy vì nó chỉ đọc các khoá cũ. Lưu ý: kiểu `ModelVersion.metrics` trong `src/lib/types.ts` đang khai báo `Record<string, Record<string, number | null>>`, trong khi giờ có giá trị lồng nhau (object, mảng). Khi dùng tới các khoá mới cần nới kiểu này, ví dụ dùng interface ở cuối mục.

Mọi metric tính trên giai đoạn test (11/2013 – 01/2014). Khoá có hậu tố `_baseline` là baseline để so sánh (xanh = tốt hơn baseline).

### `metrics.m3` (D3 · Visit length)

| Khoá | Ý nghĩa | Figma D3 |
|---|---|---|
| `mae`, `rmse` | Sai số (phút), tính **theo từng địa điểm**: trung vị thời lượng đo được trong giai đoạn test so với dự đoán. Chỉ tính địa điểm có ≥ `min_visits` lượt. | "MAE 11.8 min", "RMSE 17.2 min" |
| `within_15` | Tỉ lệ địa điểm có sai số ≤ 15 phút (0–1) | "Within ±15 min 78%" |
| `mae_baseline`, `rmse_baseline`, `within_15_baseline` | Cùng metric nhưng cho baseline: trung vị theo loại địa điểm | "v1.2: 13.4 min" (so với baseline thay vì version trước, xem ghi chú) |
| `n_venues`, `min_visits` | Số địa điểm được đánh giá, ngưỡng số lượt | "Evaluated on the test set" |
| `learning_curve` | `{ iteration: number[], train: number[], valid: number[] }`, pinball loss theo vòng boosting, tối đa ~80 điểm | Biểu đồ "Learning curve" |
| `best_iteration` | Vòng dừng sớm | "stops improving at round 9 → early stop" |
| `largest_errors` | `[{ place, city, error_min, actual_min, predicted_min, n_visits }]`, 5 địa điểm sai nhiều nhất ở thành phố đang phục vụ. `error_min` = dự đoán − thực tế. | "Largest errors (test set)" |
| `coverage_50` | Tỉ lệ lượt test rơi vào khoảng `duration_lo`–`duration_hi` (kỳ vọng ~0,5) | không có trên Figma |
| `pinball`, `pinball_baseline` | Metric cũ, giữ để so với các version trước | |

Ghi chú: Figma D3 so "Run #18" với version đang active. Backend chưa lưu version riêng cho từng model, nên muốn so hai version thì đọc metric của hai phần tử trong `versions`.

### `metrics.m1` (Popularity)

Khoá cũ giữ nguyên (`spearman*`). Thêm `ndcg20`/`ndcg20_baseline`: chất lượng top 20 theo từng thành phố (0–1), vì người dùng chủ yếu nhìn đầu danh sách. Có thêm `n_cutoffs` (số mốc cắt dùng để train).

### `metrics.m2` (Hour profile)

Khoá cũ giữ nguyên (`loglik*`, `kappa_venue`, `width`). Thêm `kappa_ward` (độ mạnh của prior theo phường; `1e9` nghĩa là tầng phường bị tắt vì không giúp ích), và `hours_eval = { n, open_mae_min, close_mae_min }`: sai số (phút) giữa giờ mở/đóng *ước lượng* và giờ *thật* trên những địa điểm có cả hai.

### `by_city`, `by_bucket` (có trong cả m1, m2, m3)

- `by_city`: `{ "Ho Chi Minh City": {...}, "Hanoi": {...}, "Da Nang": {...} }`, cùng bộ metric nhưng chỉ tính cho thành phố đó.
- `by_bucket`: `{ "0-9": {...}, "10-29": {...}, "30+": {...} }`, tách theo số check-in của địa điểm (chỉ thành phố đang phục vụ). Dùng để thấy model tệ đến đâu với địa điểm ít dữ liệu (D1: "Vietnam has only 48,357 check-ins").

### `metrics.summary` (D1 · Data, D2)

```ts
summary: {
  visit_bin_edges: number[];               // [0, 20, …, 240]: mốc dưới của từng phần tử visit_hist
  data_quality: {
    visits: { raw: number; over_max: number; over_category_limit: number; kept: number; max_dwell_min: number };
    opening_hours: { crawl_found: boolean; matched: number };
  };
  confidence: Record<"m1" | "m2" | "m3" | "window", Record<string /* city */, Partial<Record<Confidence, number>>>>;
  hours_source: Partial<Record<"crawl" | "estimated", number>>;
}
```

Gợi ý dùng cho D1 "Quality issues":
- `data_quality.visits.over_max`: "N visits longer than 6 h (likely missing check-outs)". Mốc là 6 giờ (`max_dwell_min = 360`), không phải 8 giờ như trên mockup.
- `hours_source.estimated`: số địa điểm chưa có giờ mở cửa thật ("N places have no opening hours").
- `data_quality.opening_hours.matched`: số địa điểm khớp được giờ thật (D1 dòng "Place details (web crawl)").

### Kiểu gợi ý cho `src/lib/types.ts`

```ts
export type HoursSource = "crawl" | "estimated";

export interface Place {
  // ...các trường cũ...
  duration_lo: number;
  duration_hi: number;
  hours_source: HoursSource;
  closed_days: number[]; // 0 = Monday
  conf_m1: Confidence;
  conf_m2: Confidence;
  conf_m3: Confidence;
}

export interface PlaceDetail extends Place {
  hour_profile: number[];
  n_users: number;
  n_visits: number;
  one_time_share: number;
  visit_hist: number[];
}

export interface OptimizeRequest {
  // ...các trường cũ...
  start_date?: string | null; // "YYYY-MM-DD"
}

export interface Itinerary {
  // ...các trường cũ...
  warnings: string[];
}

type Metric = number | null;
export interface ModelVersion {
  // ...các trường cũ...
  metrics: {
    m1?: Record<string, unknown> & { ndcg20?: Metric; by_city?: Record<string, Record<string, Metric>> };
    m2?: Record<string, unknown> & { hours_eval?: { n: number; open_mae_min: number; close_mae_min: number } };
    m3?: Record<string, unknown> & {
      mae?: Metric; rmse?: Metric; within_15?: Metric;
      learning_curve?: { iteration: number[]; train: number[]; valid?: number[] };
      largest_errors?: { place: string; city: string; error_min: number; actual_min: number; predicted_min: number; n_visits: number }[];
    };
    summary?: unknown; // xem mục 5
  };
}
```

`src/lib/trip-store.tsx` đang kiểm tra hình dạng `Place` khi đọc từ localStorage. Hàm kiểm tra đó không nên *bắt buộc* các trường mới, vì chuyến đi đã lưu từ trước sẽ không có chúng.

## 6. Danh sách việc phía frontend

Danh sách này chỉ gồm việc để hiển thị các trường model mới trên những màn đang có. Việc cho các màn Figma mới (T4 Saved trips, hộp "Building your itinerary", "No plan fits", Data console D1–D4) nằm ở [figma-api.md §5](figma-api.md#5-việc-phía-frontend-cho-các-màn-mới).

1. `src/lib/types.ts`: thêm các kiểu ở mục 5.
2. `src/components/map/MapView.tsx` (popup, dòng ~49): `"best"` → "Best time"; giờ mở cửa theo `hours_source`; thêm "Closed on …" từ `closed_days`; thời lượng dạng khoảng.
3. Panel địa điểm ở T2 (`src/features/places/PlacesScreen.tsx`): ba thẻ M1/M2/M3, mỗi thẻ có độ tin cậy riêng; biểu đồ theo giờ với giờ nên đến được tô màu.
4. T1: gửi `start_date` trong `api.optimize`.
5. T3 (`src/features/itinerary/ItineraryScreen.tsx`): hiển thị `itinerary.warnings`; xử lý lỗi 422 khi mọi địa điểm đều đóng cửa.
6. `src/features/admin/AdminScreens.tsx`: sửa câu mô tả M2; thêm cột MAE / RMSE / Within ±15 cho M3, learning curve, largest errors, và metric theo thành phố.
7. Chỗ hiển thị "golden hour" trên landing (`HowItWorks.tsx`) chỉ là minh hoạ, không lấy dữ liệu từ API. Có thể giữ, hoặc đổi chữ cho khớp với "Best time".
