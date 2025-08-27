# scripts/build_map.py
#
# Compact, mobile-friendly title/info UI:
# - Bottom-left "i" button toggles an info panel (collapsed by default)
# - Panel shows large logo, title, details, archive link
# - Legend remains raised from the bottom for mobile
# - MiniMap removed
#
# NOTE: All CSS/JS braces in template strings are doubled {{ }} to avoid f-string formatting issues.

import os
import sys
import base64
import hashlib
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict, OrderedDict

import folium
from folium.plugins import MarkerCluster, Fullscreen, MeasureControl, LocateControl, MousePosition
try:
    import ipywidgets as widgets
    from IPython.display import display
    IN_NOTEBOOK = True
except Exception:
    IN_NOTEBOOK = False

# ---------- Paths ----------
if "google.colab" in sys.modules:
    default_output_dir = "/content/bird_maps"
elif os.name == "nt":
    default_output_dir = "C:\\Temp\\bird_maps"
else:
    default_output_dir = "/tmp/bird_maps"

output_dir = os.getenv("OUTPUT_DIR", default_output_dir)
KEEP_COUNT = int(os.getenv("KEEP_COUNT", "30"))
os.makedirs(output_dir, exist_ok=True)

# ---------- Config ----------
API_KEY = os.getenv("EBIRD_API_KEY", "").strip()
if not API_KEY:
    API_KEY = "REPLACE_WITH_YOUR_EBIRD_API_KEY"  # prefer env var

CENTER_LAT = 42.3974042
CENTER_LON = -71.1366337
DEFAULT_RADIUS_KM = 10
BACK_DAYS = 2
MAX_RESULTS = 200
ZOOM_START = 11
SPECIES_LAYER_THRESHOLD = 200
ARCHIVE_URL = "https://mmcgee.github.io/ebird-notable-maps/"
MAP_MAIN_TITLE = "North Cambridge and Vicinity"

# Absolute path to logo for embedding - set via MAP_LOGO_FILE env in CI
MAP_LOGO_FILE = os.getenv("MAP_LOGO_FILE", "")

def color_for_species(name: str) -> str:
    h = int(hashlib.sha1((name or 'Unknown').encode("utf-8")).hexdigest(), 16) % 360
    def hsl_to_rgb(h, s=0.70, l=0.45):
        c = (1 - abs(2*l - 1)) * s
        x = c * (1 - abs(((h/60) % 2) - 1))
        m = l - c/2
        if   0 <= h < 60:   r,g,b = c,x,0
        elif 60 <= h < 120: r,g,b = x,c,0
        elif 120<= h <180:  r,g,b = 0,c,x
        elif 180<= h <240:  r,g,b = 0,x,c
        elif 240<= h <300:  r,g,b = x,0,c
        else:               r,g,b = c,0,x
        r,g,b = (int((r+m)*255), int((g+m)*255), int((b+m)*255))
        return "#{:02x}{:02x}{:02x}".format(r,g,b)
    return hsl_to_rgb(h)

def km_to_m(km: float) -> float:
    return float(km) * 1000.0

def fetch_notable(lat: float, lon: float, radius_km: int, back_days: int = BACK_DAYS, max_results: int = MAX_RESULTS):
    url = "https://api.ebird.org/v2/data/obs/geo/recent/notable"
    params = {"lat": lat, "lng": lon, "dist": radius_km, "back": back_days, "maxResults": max_results}
    headers = {"X-eBirdApiToken": API_KEY}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code == 403:
            raise RuntimeError("403 from eBird. API key missing or invalid.")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching data from eBird API: {e}")
        return []

_CACHE = {}
def get_data(lat, lon, radius_km, back_days):
    key = (round(lat, 6), round(lon, 6), int(radius_km), int(back_days))
    if key in _CACHE:
        return _CACHE[key]
    data = fetch_notable(lat, lon, radius_km, back_days)
    _CACHE[key] = data
    return data

def build_legend_html(species_to_color: OrderedDict) -> str:
    items = "".join(
        f"<div style='display:flex;align-items:center;margin:2px 0;'>"
        f"<span style='display:inline-block;width:12px;height:12px;background:{hexcolor};"
        f"margin-right:6px;border:1px solid #333;flex:0 0 12px;'></span>"
        f"<span style='font-size:12px;line-height:1.2'>{sp}</span></div>"
        for sp, hexcolor in species_to_color.items()
    )
    html = f"""
    <div id="legend" style="
        position: fixed;
        bottom: 48px;   /* raised for spacing on mobile */
        right: 16px;
        z-index: 900;
        background: rgba(255,255,255,0.95);
        padding: 8px 10px;
        border: 1px solid #888;
        border-radius: 6px;
        max-height: 70vh;
        max-width: 28vw;
        overflow-y: auto;
        overflow-x: hidden;
        resize: vertical;
        box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        ">
        <div style="font-weight:600;margin-bottom:6px;">Species Legend</div>
        {items if items else "<div style='font-size:12px;'>No species</div>"}
    </div>
    """
    return html

def add_radius_rings(m, lat, lon, main_radius_km):
    # Center marker
    folium.CircleMarker(
        [lat, lon],
        radius=4,
        color="#2c7fb8",
        fill=True,
        fill_opacity=1,
        tooltip="Center"
    ).add_to(m)

    # Main radius
    folium.Circle(
        [lat, lon],
        radius=km_to_m(main_radius_km),
        color="#08519c",
        fill=False,
        weight=3,
        opacity=0.9
    ).add_to(m)
    folium.Marker(
        [lat + main_radius_km/111.0, lon],
        icon=folium.DivIcon(
            html=f"<div style='font-size:12px; color:#08519c; font-weight:bold;'>{main_radius_km} km</div>"
        )
    ).add_to(m)

    # 1 km ring
    folium.Circle(
        [lat, lon],
        radius=km_to_m(1),
        color="#000000",
        fill=False,
        weight=2,
        opacity=0.9,
        dash_array="5,5"
    ).add_to(m)
    folium.Marker(
        [lat + 1/111.0, lon],
        icon=folium.DivIcon(
            html="<div style='font-size:12px; color:#000;'>1 km</div>"
        )
    ).add_to(m)

    # 5 km ring
    folium.Circle(
        [lat, lon],
        radius=km_to_m(5),
        color="#555555",
        fill=False,
        weight=2,
        opacity=0.9,
        dash_array="5,7"
    ).add_to(m)
    folium.Marker(
        [lat + 5/111.0, lon],
        icon=folium.DivIcon(
            html="<div style='font-size:12px; color:#555;'>5 km</div>"
        )
    ).add_to(m)


def add_notice(m, text: str):
    html = f"""
    <div style="
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      background: rgba(255,255,255,0.95);
      padding: 10px 14px;
      border: 1px solid #999;
      border-radius: 6px;
      z-index: 1500;
      font-size: 14px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.2);
    ">{text}</div>
    """
    m.get_root().html.add_child(folium.Element(html))

def compute_dt_et():
    tz = ZoneInfo("America/New_York")
    run_date = os.getenv("RUN_DATE_ET", "")
    run_slot = os.getenv("RUN_SLOT", "")
    try:
        if run_date and run_slot in ("12", "21"):
            y, mo, d = map(int, run_date.split("-"))
            h = int(run_slot)
            dt = datetime(y, mo, d, h, 0, 0, tzinfo=tz)
        else:
            dt = datetime.now(tz)
    except Exception:
        dt = datetime.now(tz)
    display_str = dt.strftime("%b %d, %Y %I:%M %p %Z")
    file_str = dt.strftime("%Y-%m-%d_%H-%M-%S_ET")
    return dt, display_str, file_str

def _logo_data_url(logo_abs_path: str) -> str:
    # Return a data URL for the PNG logo if present - else return empty string
    try:
        if not logo_abs_path or not os.path.isfile(logo_abs_path):
            return ""
        with open(logo_abs_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""

def build_info_ui(radius_km: int, back_days: int, ts_display_et: str, logo_data_url: str) -> str:
    """
    Bottom-left compact info UI:
      - Round "i" button toggles a hidden panel
      - Panel shows big logo, title, details, archive link
      - Collapsed by default for mobile friendliness
    """
    logo_img = ""
    if logo_data_url:
        # Large logo for legibility when opened
        logo_img = "<img src='{src}' alt='Goodbirds logo' style='height:100px;display:block;'>".format(src=logo_data_url)

    html = """
    <style>
      /* Info button */
      .gb-info-btn {{
        position: fixed;
        left: 16px;
        bottom: 16px;
        width: 44px;
        height: 44px;
        border-radius: 50%;
        background: #ffffff;
        border: 1px solid #999;
        box-shadow: 0 2px 6px rgba(0,0,0,0.25);
        z-index: 1201;
        display: flex;
        align-items: center;
        justify-content: center;
        font: 700 18px/1 system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
        cursor: pointer;
        user-select: none;
      }}
      .gb-info-btn:focus {{ outline: 2px solid #2c7fb8; }}

      /* Info panel */
      .gb-info-panel {{
        position: fixed;
        left: 16px;
        bottom: 16px;
        z-index: 1200;
        background: rgba(255,255,255,0.98);
        border: 1px solid #999;
        border-radius: 10px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        padding: 12px;
        width: min(92vw, 360px);
        max-height: 70vh;
        display: none; /* hidden until toggled */
      }}
      .gb-info-header {{
        display: grid;
        grid-template-columns: auto 1fr;
        grid-gap: 12px;
        align-items: center;
      }}
      .gb-info-title {{
        font-weight: 700;
        font-size: 16px;
        margin: 0;
      }}
      .gb-info-meta {{
        font-size: 13px;
        margin-top: 2px;
      }}
      .gb-info-row {{
        margin-top: 6px;
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 12px;
      }}
      .gb-info-close {{
        position: absolute;
        right: 8px;
        top: 6px;
        border: none;
        background: transparent;
        font-size: 18px;
        cursor: pointer;
        line-height: 1;
      }}
      .gb-info-close:focus {{ outline: 2px solid #2c7fb8; }}

      /* Small screens - keep it compact */
      @media (max-width: 480px) {{
        .gb-info-panel {{
          width: 92vw;
        }}
        .gb-info-title {{ font-size: 15px; }}
        .gb-info-meta {{ font-size: 12px; }}
        .gb-info-row {{ font-size: 11px; }}
      }}
    </style>

    <div class="gb-info-btn" id="gbInfoBtn" role="button" aria-label="Show map info" aria-expanded="false">i</div>

    <div class="gb-info-panel" id="gbInfoPanel" aria-hidden="true">
      <button class="gb-info-close" id="gbInfoClose" aria-label="Close info">×</button>
      <div class="gb-info-header">
        <div>{logo_img}</div>
        <div>
          <h3 class="gb-info-title">{title}</h3>
          <div class="gb-info-meta">eBird Notable - {radius} km radius - last {back} day(s)</div>
          <div class="gb-info-row">
            <span>Built: {ts}</span>
            <a href="{archive}" target="_blank" rel="noopener">Archive</a>
          </div>
        </div>
      </div>
    </div>

    <script>
      (function() {{
        var btn = document.getElementById('gbInfoBtn');
        var panel = document.getElementById('gbInfoPanel');
        var closeBtn = document.getElementById('gbInfoClose');

        function openPanel() {{
          panel.style.display = 'block';
          btn.setAttribute('aria-expanded', 'true');
          panel.setAttribute('aria-hidden', 'false');
        }}
        function closePanel() {{
          panel.style.display = 'none';
          btn.setAttribute('aria-expanded', 'false');
          panel.setAttribute('aria-hidden', 'true');
        }}

        btn.addEventListener('click', function(e) {{
          if (panel.style.display === 'block') {{
            closePanel();
          }} else {{
            openPanel();
          }}
        }});
        closeBtn.addEventListener('click', function(e) {{
          closePanel();
        }});

        // Close panel when clicking outside it
        document.addEventListener('click', function(e) {{
          if (!panel.contains(e.target) && e.target !== btn) {{
            closePanel();
          }}
        }});
      }})();
    </script>
    """.format(
        logo_img=logo_img,
        title=MAP_MAIN_TITLE,
        radius=radius_km,
        back=back_days,
        ts=ts_display_et,
        archive=ARCHIVE_URL,
    )
    return html

def add_clear_species_control(m: folium.Map, species_names):
    species_list = list(species_names or [])
    js = f"""
    <script>
    (function() {{
      var speciesSet = new Set({species_list!r});
      function clearSpecies() {{
        var root = document.querySelector('.leaflet-control-layers-overlays');
        if (!root) return;
        var labels = root.querySelectorAll('label');
        labels.forEach(function(label){{
          var input = label.querySelector('input[type=checkbox]');
          if(!input) return;
          var name = label.textContent.trim();
          if (speciesSet.has(name) && input.checked) {{
            input.click();
          }}
        }});
      }}
      var ClearCtl = L.Control.extend({{
        onAdd: function(map) {{
          var div = L.DomUtil.create('div', 'leaflet-bar');
          div.style.background = 'white';
          div.style.padding = '4px 6px';
          div.style.cursor = 'pointer';
          div.style.font = '12px/1.2 sans-serif';
          div.style.boxShadow = '0 1px 4px rgba(0,0,0,0.2)';
          div.title = 'Uncheck all species layers';
          div.innerHTML = 'Clear species';
          L.DomEvent.on(div, 'click', function(e) {{
            L.DomEvent.stop(e);
            clearSpecies();
          }});
          return div;
        }},
        onRemove: function(map) {{}}
      }});
      function addWhenReady() {{
        if (!document.querySelector('.leaflet-control-layers')) {{
          return setTimeout(addWhenReady, 150);
        }}
        (new ClearCtl({{ position: 'topright' }})).addTo({m.get_name()});
      }}
      addWhenReady();
    }})();
    </script>
    """
    m.get_root().html.add_child(folium.Element(js))

def prune_archive(dirpath: str, keep: int = 30) -> int:
    try:
        files = [f for f in os.listdir(dirpath)
                 if f.startswith("ebird_radius_map_") and f.endswith(".html")]
        files.sort(reverse=True)
        to_remove = files[keep:]
        for f in to_remove:
            try:
                os.remove(os.path.join(dirpath, f))
            except Exception:
                pass
        return len(to_remove)
    except Exception:
        return 0

def save_and_publish(m, outfile: str):
    m.save(outfile)
    print(f"Map saved as '{outfile}'")
    latest_path = os.path.join(output_dir, "latest.html")
    try:
        import shutil
        shutil.copyfile(outfile, latest_path)
        print(f"Updated '{latest_path}'")
    except Exception:
        pass
    if "google.colab" in sys.modules:
        try:
            from google.colab import files
            files.download(outfile)
        except Exception:
            pass
    removed = prune_archive(output_dir, KEEP_COUNT)
    print(f"Archive pruning - kept {KEEP_COUNT}, removed {removed}")

def make_map(lat=CENTER_LAT, lon=CENTER_LON, radius_km=DEFAULT_RADIUS_KM,
             back_days=BACK_DAYS, zoom_start=ZOOM_START):
    _, ts_display_et, ts_file_et = compute_dt_et()
    outfile = os.path.join(output_dir, f"ebird_radius_map_{ts_file_et}_{radius_km}km.html")

    data = get_data(lat, lon, radius_km, back_days)

    m = folium.Map(location=[lat, lon], zoom_start=zoom_start, control_scale=True)

    # Bottom-left compact info UI
    logo_data_url = _logo_data_url(MAP_LOGO_FILE)
    m.get_root().html.add_child(folium.Element(build_info_ui(radius_km, back_days, ts_display_et, logo_data_url)))

    add_radius_rings(m, lat, lon, radius_km)
    Fullscreen().add_to(m)
    # MiniMap removed
    m.add_child(MeasureControl(primary_length_unit="kilometers"))
    LocateControl(auto_start=False, keepCurrentZoomLevel=False).add_to(m)
    MousePosition(separator=" , ", prefix="Lat, Lon:").add_to(m)

    if not data:
        add_notice(m, "No current notable birds for the selected window.")
        legend_html = build_legend_html(OrderedDict())
        m.get_root().html.add_child(folium.Element(legend_html))
        add_clear_species_control(m, [])
        save_and_publish(m, outfile)
        return m, outfile

    loc_species = defaultdict(lambda: defaultdict(list))
    species_set = set()
    for s in data:
        slat = s.get("lat"); slon = s.get("lng")
        sp = s.get("comName") or "Unknown"
        species_set.add(sp)
        loc_name = s.get("locName") or "Unknown location"
        obs_date = s.get("obsDt")
        how_many = s.get("howMany", "Unknown")
        checklist_id = s.get("subId")
        checklist_url = f"https://ebird.org/checklist/{checklist_id}" if checklist_id else ""
        entry_html = f"<b>{sp}</b> ({how_many}) on {obs_date}"
        if checklist_url:
            entry_html += f" [<a href='{checklist_url}' target='_blank' rel='noopener'>Checklist</a>]"

        loc_species[(slat, slon)][sp].append({"entry_html": entry_html, "loc_name": loc_name})

    species_to_color = OrderedDict(sorted([(sp, color_for_species(sp)) for sp in species_set], key=lambda x: x[0]))
    too_many = len(species_to_color) > SPECIES_LAYER_THRESHOLD

    if not too_many:
        species_groups = {}
        for sp, hexcol in species_to_color.items():
            fg = folium.FeatureGroup(name=sp, show=True)
            cluster = MarkerCluster(name=f"{sp} markers")
            fg.add_child(cluster)
            species_groups[sp] = (fg, cluster)
            m.add_child(fg)
        for (slat, slon), species_dict in loc_species.items():
            for sp, entries in species_dict.items():
                hexcol = species_to_color.get(sp, "#444444")
                loc_name = entries[0]["loc_name"]
                popup_html = f"""
                <div style="font-size:13px;">
                  <div><b>Location:</b> {loc_name}</div>
                  <hr style="margin:6px 0;">
                  <div>{"<br>".join(e["entry_html"] for e in entries)}</div>
                </div>"""
                icon = folium.DivIcon(
                    html=f"<div style='width:14px;height:14px;border-radius:50%;background:{hexcol};border:1.5px solid #222;'></div>",
                    icon_size=(14, 14), icon_anchor=(7, 7),
                )
                folium.Marker([slat, slon], icon=icon, tooltip=sp,
                              popup=folium.Popup(popup_html, max_width=320)).add_to(species_groups[sp][1])
        folium.LayerControl(collapsed=False).add_to(m)
        add_clear_species_control(m, list(species_to_color.keys()))
    else:
        cluster = MarkerCluster(name="Notable sightings").add_to(m)
        for (slat, slon), species_dict in loc_species.items():
            for sp, entries in species_dict.items():
                hexcol = species_to_color.get(sp, "#444444")
                loc_name = entries[0]["loc_name"]
                popup_html = f"""
                <div style="font-size:13px;">
                  <div><b>Location:</b> {loc_name}</div>
                  <hr style="margin:6px 0;">
                  <div>{"<br>".join(e["entry_html"] for e in entries)}</div>
                </div>"""
                icon = folium.DivIcon(
                    html=f"<div style='width:14px;height:14px;border-radius:50%;background:{hexcol};border:1.5px solid #222;'></div>",
                    icon_size=(14, 14), icon_anchor=(7, 7),
                )
                folium.Marker([slat, slon], icon=icon, tooltip=sp,
                              popup=folium.Popup(popup_html, max_width=320)).add_to(cluster)
        folium.LayerControl(collapsed=False).add_to(m)
        add_clear_species_control(m, list(species_to_color.keys()))

    legend_html = build_legend_html(species_to_color)
    m.get_root().html.add_child(folium.Element(legend_html))
    save_and_publish(m, outfile)
    return m, outfile

if __name__ == "__main__":
    m, outfile = make_map(CENTER_LAT, CENTER_LON, DEFAULT_RADIUS_KM, BACK_DAYS)
    if IN_NOTEBOOK and m:
        display(m)
