# scripts/build_map.py
#
# Popups now include the species name at the very top.
# Other features preserved:
# - Multiple checklists for that species/location are listed
# - Info panel aligned above the "i" button
# - Robust logo loading
# - Labeled radius rings
# - Raised legend
# - No MiniMap

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
    import ipywidgets as widgets  # noqa: F401
    from IPython.display import display  # noqa: F401
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
    API_KEY = "REPLACE_WITH_YOUR_EBIRD_API_KEY"

CENTER_LAT = 42.3974042
CENTER_LON = -71.1366337
DEFAULT_RADIUS_KM = 10
BACK_DAYS = 2
MAX_RESULTS = 200
ZOOM_START = 11
SPECIES_LAYER_THRESHOLD = 200
ARCHIVE_URL = "https://mmcgee.github.io/ebird-notable-maps/"
MAP_MAIN_TITLE = "North Cambridge and Vicinity"

# Logo config
MAP_LOGO_FILE = os.getenv("MAP_LOGO_FILE", "").strip()
MAP_LOGO_URL = os.getenv("MAP_LOGO_URL", "").strip()
DEFAULT_LOGO_NAME = "goodbirds_logo_text.png"

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
        bottom: 48px;
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
    folium.CircleMarker([lat, lon], radius=4, color="#2c7fb8", fill=True,
                        fill_opacity=1, tooltip="Center").add_to(m)

    folium.Circle([lat, lon], radius=km_to_m(main_radius_km),
                  color="#08519c", fill=False, weight=3, opacity=0.9).add_to(m)
    folium.Marker([lat + main_radius_km/111.0, lon],
                  icon=folium.DivIcon(html=f"<div style='font-size:12px; color:#08519c; font-weight:bold;'>{main_radius_km} km</div>")
                  ).add_to(m)

    folium.Circle([lat, lon], radius=km_to_m(1), color="#000000",
                  fill=False, weight=2, opacity=0.9, dash_array="5,5").add_to(m)
    folium.Marker([lat + 1/111.0, lon],
                  icon=folium.DivIcon(html="<div style='font-size:12px; color:#000;'>1 km</div>")
                  ).add_to(m)

    folium.Circle([lat, lon], radius=km_to_m(5), color="#555555",
                  fill=False, weight=2, opacity=0.9, dash_array="5,7").add_to(m)
    folium.Marker([lat + 5/111.0, lon],
                  icon=folium.DivIcon(html="<div style='font-size:12px; color:#555;'>5 km</div>")
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

def _file_to_data_url(path: str) -> str:
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""

def get_logo_src() -> str:
    if MAP_LOGO_FILE and os.path.isfile(MAP_LOGO_FILE):
        d = _file_to_data_url(MAP_LOGO_FILE)
        if d:
            return d
    candidate_paths = [os.path.join("docs", DEFAULT_LOGO_NAME), DEFAULT_LOGO_NAME]
    for p in candidate_paths:
        if os.path.isfile(p):
            d = _file_to_data_url(p)
            if d:
                return d
    if MAP_LOGO_URL:
        return MAP_LOGO_URL
    return ARCHIVE_URL + DEFAULT_LOGO_NAME

def build_info_ui(radius_km: int, back_days: int, ts_display_et: str, logo_src: str) -> str:
    logo_img = "<img src='{src}' alt='Goodbirds logo' style='height:100px;display:block;'>".format(src=logo_src)
    html = """
    <style>
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
      .gb-info-panel {{
        position: fixed;
        left: 16px;
        bottom: 70px;
        z-index: 1200;
        background: rgba(255,255,255,0.98);
        border: 1px solid #999;
        border-radius: 10px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        padding: 12px;
        width: min(92vw, 360px);
        max-height: 70vh;
        display: none;
      }}
    </style>
    <div class="gb-info-btn" id="gbInfoBtn">i</div>
    <div class="gb-info-panel" id="gbInfoPanel">
      <div class="gb-info-header">
        <div>{logo_img}</div>
        <div>
          <h3 class="gb-info-title">{title}</h3>
          <div class="gb-info-meta">eBird Notable - {radius} km radius - last {back} day(s)</div>
          <div class="gb-info-row"><span>Built: {ts}</span>
          <a href="{archive}" target="_blank" rel="noopener">Archive</a></div>
        </div>
      </div>
    </div>
    <script>
      (function(){{
        var btn=document.getElementById('gbInfoBtn');
        var panel=document.getElementById('gbInfoPanel');
        btn.addEventListener('click',function(){{
          if(panel.style.display==='block'){{panel.style.display='none';}}
          else{{panel.style.display='block';}}
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

def prune_archive(dirpath: str, keep: int = 30) -> int:
    try:
        files = [f for f in os.listdir(dirpath)
                 if f.startswith("ebird_radius_map_") and f.endswith(".html")]
        files.sort(reverse=True)
        to_remove = files[keep:]
        for f in to_remove:
            try: os.remove(os.path.join(dirpath, f))
            except Exception: pass
        return len(to_remove)
    except Exception:
        return 0

def save_and_publish(m, outfile: str):
    m.save(outfile)
    latest_path = os.path.join(output_dir, "latest.html")
    try:
        import shutil; shutil.copyfile(outfile, latest_path)
    except Exception: pass
    prune_archive(output_dir, KEEP_COUNT)

def make_map(lat=CENTER_LAT, lon=CENTER_LON, radius_km=DEFAULT_RADIUS_KM,
             back_days=BACK_DAYS, zoom_start=ZOOM_START):
    _, ts_display_et, ts_file_et = compute_dt_et()
    outfile = os.path.join(output_dir, f"ebird_radius_map_{ts_file_et}_{radius_km}km.html")
    data = get_data(lat, lon, radius_km, back_days)
    m = folium.Map(location=[lat, lon], zoom_start=zoom_start, control_scale=True)

    logo_src = get_logo_src()
    m.get_root().html.add_child(folium.Element(build_info_ui(radius_km, back_days, ts_display_et, logo_src)))
    add_radius_rings(m, lat, lon, radius_km)
    Fullscreen().add_to(m)
    m.add_child(MeasureControl(primary_length_unit="kilometers"))
    LocateControl(auto_start=False).add_to(m)
    MousePosition().add_to(m)

    if not data:
        add_notice(m, "No current notable birds for the selected window.")
        m.get_root().html.add_child(folium.Element(build_legend_html(OrderedDict())))
        save_and_publish(m, outfile)
        return m, outfile

    loc_species = defaultdict(lambda: defaultdict(list))
    species_set = set()
    for s in data:
        slat, slon = s.get("lat"), s.get("lng")
        sp = s.get("comName") or "Unknown"
        species_set.add(sp)
        loc_name = s.get("locName") or "Unknown location"
        obs_date = s.get("obsDt") or ""
        how_many = s.get("howMany")
        checklist_id = s.get("subId")
        checklist_url = f"https://ebird.org/checklist/{checklist_id}" if checklist_id else ""
        loc_species[(slat, slon)][sp].append({"loc_name": loc_name,"obs_date": obs_date,"how_many": how_many,"checklist_url": checklist_url})

    species_to_color = OrderedDict(sorted([(sp, color_for_species(sp)) for sp in species_set], key=lambda x: x[0]))

    def popup_html_for_entries(sp, loc_name, entries):
        items=[]
        for e in entries:
            count_txt=f" ({e['how_many']})" if e["how_many"] else ""
            if e["checklist_url"]:
                items.append(f"<li><a href='{e['checklist_url']}' target='_blank'>Checklist</a> – {e['obs_date']}{count_txt}</li>")
            else:
                items.append(f"<li>{e['obs_date']}{count_txt}</li>")
        lst="<ul>"+ "".join(items)+"</ul>"
        return f"<div style='font-size:13px;'><div><b>{sp}</b></div><div><b>Location:</b> {loc_name}</div>{lst}</div>"

    for (slat, slon), species_dict in loc_species.items():
        for sp, entries in species_dict.items():
            hexcol=species_to_color.get(sp,"#444")
            loc_name=entries[0]["loc_name"]
            popup_html=popup_html_for_entries(sp,loc_name,entries)
            icon=folium.DivIcon(html=f"<div style='width:14px;height:14px;border-radius:50%;background:{hexcol};border:1.5px solid #222;'></div>",icon_size=(14,14),icon_anchor=(7,7))
            folium.Marker([slat,slon],icon=icon,tooltip=sp,popup=folium.Popup(popup_html,max_width=320)).add_to(m)

    m.get_root().html.add_child(folium.Element(build_legend_html(species_to_color)))
    save_and_publish(m, outfile)
    return m, outfile

if __name__=="__main__":
    m,outfile=make_map()
    if IN_NOTEBOOK: display(m)

