from __future__ import annotations

import json

from sqlalchemy import text

from .db import get_engine

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<title>AVM 거래 지도</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  html, body, #map {{ height: 100%; margin: 0; }}
  .info-box {{
    position: absolute; top: 10px; right: 10px; z-index: 1000;
    background: white; padding: 8px 12px; border-radius: 6px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3); font: 13px sans-serif;
  }}
</style>
</head>
<body>
<div id="map"></div>
<div class="info-box">거래 {count}건 표시</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  const points = {points_json};
  const map = L.map('map').setView([{center_lat}, {center_lng}], 13);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);

  const prices = points.map(p => p.price_per_m2);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);

  function colorFor(p) {{
    if (maxP === minP) return '#3388ff';
    const ratio = (p - minP) / (maxP - minP);
    const r = Math.round(255 * ratio);
    const b = Math.round(255 * (1 - ratio));
    return `rgb(${{r}}, 60, ${{b}})`;
  }}

  points.forEach(p => {{
    const marker = L.circleMarker([p.lat, p.lng], {{
      radius: 6,
      color: colorFor(p.price_per_m2),
      fillColor: colorFor(p.price_per_m2),
      fillOpacity: 0.8,
    }}).addTo(map);
    marker.bindPopup(
      `<b>${{p.apt_name}}</b><br/>` +
      `${{p.address}}<br/>` +
      `거래일: ${{p.deal_date}}<br/>` +
      `전용면적: ${{p.area_m2}}m²  ${{p.floor}}층<br/>` +
      `거래금액: ${{p.price_krw.toLocaleString()}}원<br/>` +
      `평당(㎡당) 단가: ${{Math.round(p.price_per_m2).toLocaleString()}}원/m²`
    );
  }});
</script>
</body>
</html>
"""


def build_map_html(engine=None) -> str:
    """지오코딩된 거래 데이터를 Leaflet 지도 HTML로 렌더링한다."""
    engine = engine or get_engine()

    query = text(
        """
        SELECT t.apt_name, t.address, t.deal_date, t.area_m2, t.floor, t.price_krw,
               g.lat, g.lng
        FROM trades t
        JOIN geocache g ON g.address = t.address
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    points = [
        {
            "apt_name": row["apt_name"],
            "address": row["address"],
            "deal_date": str(row["deal_date"]),
            "area_m2": row["area_m2"],
            "floor": row["floor"],
            "price_krw": row["price_krw"],
            "price_per_m2": row["price_krw"] / row["area_m2"] if row["area_m2"] else 0,
            "lat": row["lat"],
            "lng": row["lng"],
        }
        for row in rows
    ]

    if points:
        center_lat = sum(p["lat"] for p in points) / len(points)
        center_lng = sum(p["lng"] for p in points) / len(points)
    else:
        center_lat, center_lng = 37.5665, 126.9780  # 서울시청 기본값

    return _HTML_TEMPLATE.format(
        count=len(points),
        points_json=json.dumps(points, ensure_ascii=False),
        center_lat=center_lat,
        center_lng=center_lng,
    )
