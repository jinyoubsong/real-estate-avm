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
  html, body {{ height: 100%; margin: 0; font-family: sans-serif; }}
  #layout {{ display: flex; height: 100%; }}
  #map {{ flex: 1 1 auto; height: 100%; }}
  #sidebar {{
    flex: 0 0 320px; height: 100%; overflow-y: auto;
    border-left: 1px solid #ddd; background: #fafafa;
    box-sizing: border-box;
  }}
  #sidebar-header {{
    position: sticky; top: 0; background: #fafafa; z-index: 1;
    padding: 12px 14px; border-bottom: 1px solid #ddd; font-size: 13px; color: #333;
  }}
  #sidebar-header b {{ font-size: 14px; }}
  .sidebar-item {{
    padding: 10px 14px; border-bottom: 1px solid #eee; font-size: 12px; line-height: 1.6;
    cursor: pointer;
  }}
  .sidebar-item:hover {{ background: #eef4ff; }}
  .sidebar-item .name {{ font-weight: bold; font-size: 13px; }}
  .sidebar-item .price {{ color: #b3261e; font-weight: bold; }}
  .proximity-tooltip {{
    position: absolute; z-index: 1000; display: none; pointer-events: none;
    background: white; padding: 8px 10px; border-radius: 6px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.35); font: 12px/1.5 sans-serif;
    max-width: 240px; white-space: nowrap;
  }}
</style>
</head>
<body>
<div id="layout">
  <div style="position: relative; flex: 1 1 auto;">
    <div id="map"></div>
    <div id="tooltip" class="proximity-tooltip"></div>
  </div>
  <div id="sidebar">
    <div id="sidebar-header"><b>화면에 보이는 매물</b><br/>지도를 움직이면 목록이 갱신됩니다.</div>
    <div id="sidebar-list"></div>
  </div>
</div>
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

  const markers = points.map((p, i) => ({{
    point: p,
    marker: L.circleMarker([p.lat, p.lng], {{
      radius: 6,
      color: colorFor(p.price_per_m2),
      fillColor: colorFor(p.price_per_m2),
      fillOpacity: 0.8,
    }}).addTo(map),
  }}));

  function detailHtml(p) {{
    return `<div class="name">${{p.apt_name}}</div>` +
      `${{p.address}}<br/>` +
      `거래일: ${{p.deal_date}}<br/>` +
      `전용면적: ${{p.area_m2}}m²  ${{p.floor}}층<br/>` +
      `거래금액: <span class="price">${{p.price_krw.toLocaleString()}}원</span><br/>` +
      `평당(㎡당) 단가: ${{Math.round(p.price_per_m2).toLocaleString()}}원/m²`;
  }}

  // 근접 호버 툴팁: 마커 중심에서 이 거리(px) 안이면 근처로 인식
  const tooltipEl = document.getElementById('tooltip');
  const mapEl = document.getElementById('map');
  const HOVER_RADIUS_PX = 20;

  map.on('mousemove', (e) => {{
    let nearest = null;
    let nearestDist = HOVER_RADIUS_PX;
    for (const {{point, marker}} of markers) {{
      const pt = map.latLngToContainerPoint(marker.getLatLng());
      const dist = pt.distanceTo(e.containerPoint);
      if (dist < nearestDist) {{
        nearestDist = dist;
        nearest = point;
      }}
    }}

    if (nearest) {{
      tooltipEl.innerHTML = detailHtml(nearest);
      const left = Math.min(e.containerPoint.x + 14, mapEl.clientWidth - 250);
      const top = Math.min(e.containerPoint.y + 14, mapEl.clientHeight - 120);
      tooltipEl.style.left = left + 'px';
      tooltipEl.style.top = top + 'px';
      tooltipEl.style.display = 'block';
    }} else {{
      tooltipEl.style.display = 'none';
    }}
  }});
  map.on('mouseout', () => {{ tooltipEl.style.display = 'none'; }});

  // 우측 패널: 현재 화면(bounds) 안에 있는 매물 목록, 지도 이동/줌마다 갱신
  const headerEl = document.getElementById('sidebar-header');
  const listEl = document.getElementById('sidebar-list');

  function refreshSidebar() {{
    const bounds = map.getBounds();
    const visible = markers
      .filter(({{marker}}) => bounds.contains(marker.getLatLng()))
      .map(({{point}}) => point)
      .sort((a, b) => b.deal_date.localeCompare(a.deal_date));

    headerEl.innerHTML = `<b>화면에 보이는 매물 ${{visible.length}}건</b><br/>지도를 움직이면 목록이 갱신됩니다.`;
    listEl.innerHTML = visible.map(p => `<div class="sidebar-item">${{detailHtml(p)}}</div>`).join('');
  }}

  map.on('moveend', refreshSidebar);
  refreshSidebar();
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
        points_json=json.dumps(points, ensure_ascii=False),
        center_lat=center_lat,
        center_lng=center_lng,
    )
