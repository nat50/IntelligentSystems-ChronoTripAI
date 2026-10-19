"""City assignment (30 km radius) and ward labels for display.

The dataset has no place names or addresses, so places are shown as
"<category> · <nearest ward>" (spec II.2, Table 1).
"""

from __future__ import annotations

import numpy as np

SEA_COUNTRIES = ("ID", "MY", "TH", "PH", "SG", "VN", "KH", "LA", "MM", "BN", "TL")
CITY_RADIUS_KM = 30.0

# name, country, lat, lon
CITIES: list[tuple[str, str, float, float]] = [
    ("Ho Chi Minh City", "VN", 10.7769, 106.7009),
    ("Hanoi", "VN", 21.0285, 105.8542),
    ("Da Nang", "VN", 16.0544, 108.2022),
    ("Jakarta", "ID", -6.2088, 106.8456),
    ("Bandung", "ID", -6.9175, 107.6191),
    ("Surabaya", "ID", -7.2575, 112.7521),
    ("Yogyakarta", "ID", -7.7956, 110.3695),
    ("Medan", "ID", 3.5952, 98.6722),
    ("Denpasar", "ID", -8.6705, 115.2126),
    ("Kuala Lumpur", "MY", 3.1390, 101.6869),
    ("George Town", "MY", 5.4141, 100.3288),
    ("Johor Bahru", "MY", 1.4927, 103.7414),
    ("Bangkok", "TH", 13.7563, 100.5018),
    ("Chiang Mai", "TH", 18.7883, 98.9853),
    ("Phuket", "TH", 7.8804, 98.3923),
    ("Manila", "PH", 14.5995, 120.9842),
    ("Cebu", "PH", 10.3157, 123.8854),
    ("Singapore", "SG", 1.3521, 103.8198),
    ("Phnom Penh", "KH", 11.5564, 104.9282),
]

SUPPORTED_CITIES = ("Ho Chi Minh City", "Hanoi")  # prototype scope (spec II.3)

# Approximate ward centroids used only for labels: (city, ward, lat, lon)
WARDS: list[tuple[str, str, float, float]] = [
    ("Ho Chi Minh City", "Thu Thiem", 10.7745, 106.7180),
    ("Ho Chi Minh City", "An Khanh", 10.7935, 106.7275),
    ("Ho Chi Minh City", "An Phu", 10.8015, 106.7505),
    ("Ho Chi Minh City", "Thao Dien", 10.8045, 106.7335),
    ("Ho Chi Minh City", "Binh Tho", 10.8485, 106.7650),
    ("Ho Chi Minh City", "Truong Tho", 10.8395, 106.7505),
    ("Ho Chi Minh City", "Phuoc Long B", 10.8150, 106.7795),
    ("Ho Chi Minh City", "Long Phuoc", 10.8105, 106.8600),
    ("Ho Chi Minh City", "Linh Trung", 10.8700, 106.7800),
    ("Ho Chi Minh City", "Hiep Phu", 10.8460, 106.7790),
    ("Ho Chi Minh City", "Tang Nhon Phu", 10.8450, 106.7950),
    ("Ho Chi Minh City", "Long Thanh My", 10.8400, 106.8300),
    ("Ho Chi Minh City", "Cat Lai", 10.7750, 106.7800),
    ("Ho Chi Minh City", "Binh Trung", 10.7880, 106.7600),
    ("Ho Chi Minh City", "Linh Tay", 10.8580, 106.7570),
    ("Ho Chi Minh City", "Hiep Binh", 10.8300, 106.7230),
    ("Ho Chi Minh City", "Ben Nghe", 10.7780, 106.7020),
    ("Ho Chi Minh City", "Ben Thanh", 10.7720, 106.6980),
    ("Ho Chi Minh City", "Da Kao", 10.7900, 106.6990),
    ("Ho Chi Minh City", "Vo Thi Sau", 10.7810, 106.6890),
    ("Ho Chi Minh City", "Binh Thanh", 10.8040, 106.7110),
    ("Ho Chi Minh City", "Phu Nhuan", 10.7990, 106.6800),
    ("Ho Chi Minh City", "Cho Lon", 10.7540, 106.6630),
    ("Ho Chi Minh City", "Tan Dinh", 10.7920, 106.6890),
    ("Hanoi", "Hoan Kiem", 21.0285, 105.8542),
    ("Hanoi", "Hang Bac", 21.0340, 105.8530),
    ("Hanoi", "Dien Bien", 21.0360, 105.8350),
    ("Hanoi", "Quang An", 21.0650, 105.8250),
    ("Hanoi", "Van Mieu", 21.0270, 105.8360),
    ("Hanoi", "Le Dai Hanh", 21.0110, 105.8500),
    ("Hanoi", "Dich Vong", 21.0330, 105.7930),
    ("Hanoi", "Ngoc Thuy", 21.0450, 105.8700),
    ("Hanoi", "Truc Bach", 21.0450, 105.8400),
    ("Hanoi", "Kim Ma", 21.0310, 105.8150),
]

DEFAULT_STAY = {
    "Ho Chi Minh City": (10.8008, 106.7420, "An Phu"),
    "Hanoi": (21.0310, 105.8500, "Hoan Kiem"),
}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def assign_city(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Nearest city centre within 30 km, else None."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    best = np.full(len(lat), None, dtype=object)
    best_d = np.full(len(lat), np.inf)
    for name, _, clat, clon in CITIES:
        d = haversine_km(lat, lon, clat, clon)
        hit = (d < best_d) & (d <= CITY_RADIUS_KM)
        best[hit], best_d[hit] = name, d[hit]
    return best


def ward_label(city: str, lat: float, lon: float) -> str:
    cands = [(w, wl, wn) for c, w, wl, wn in WARDS if c == city]
    if not cands:
        return city
    d = [float(haversine_km(lat, lon, wl, wn)) for _, wl, wn in cands]
    k = int(np.argmin(d))
    return cands[k][0] if d[k] <= 5.0 else city
