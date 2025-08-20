# scripts/build_map.py

# If running in Colab, ensure deps first:
# !pip -q install folium requests ipywidgets

import os
import sys
import hashlib
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict, OrderedDict

import folium
from folium.plugins import MarkerCluster, MiniMap, Fullscreen, MeasureControl, LocateControl, MousePosition
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

# Allow CI to override output location. Also allow archive prune count override.
output_dir = os.getenv("OUTPUT_DIR", default_output_dir)
KEEP_COUNT = int(os.getenv("KEEP_COUNT", "30"))
os.makedirs(output_dir, exist_ok=True)

# ---------- Config ----------
API_KEY = os.getenv("EBIRD_API_KEY", "").strip()
if not API_KEY:
    API_KEY = "REPLACE_WITH_YOUR_EBIRD_API_KEY"  # prefer env var in practice

CENTER_LAT = 42.3974042
CENTER_LON = -71.1366337
DEFAULT_RADIUS_KM = 10
BACK_DAYS = 2
MAX_RESULTS = 200
ZOOM_START = 11
SPECIES_LAYER_THRESHOLD = 25  # fallback to single layer if many species
ARCHIVE_URL = "https://mmcgee.github.io/ebird-notable-maps/"

# ---------- Utilities ----------
def color_for_species(name: str) -> str:
    """Deterministic color per species as hex."""
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
    """Fetch recent notable observations from the eBird API. No key info is ever printed."""
    url = "https://api.ebird.org/v2/data/obs/geo/recent/notable"
    params = {"lat": lat, "lng": lon, "dist": radius_km, "back": back_days, "maxResults": max_results}
    headers = {"X-eBirdApiToken": API_KEY}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code == 403:
            # Generic error only. Never reveal or echo the key.
            raise RuntimeError("403 from eBird. API key missing or invalid.")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        # Keep logs generic. Do not print response text or headers.
        print(f"Error fetching data from eBird API: {e}")
        return []

# Simple in-session cache keyed by (lat, lon, radius, back)
_CACHE = {}
def get_data(lat, lon, radius_km, back_days):
    key = (round(lat, 6), round(lon, 6), int(radius_km), int(back_days))
    if key in _CACHE:
        return _CACHE[key]
    data = fetch_notable(lat, lon, radius_km, back_days)
    _CACHE[key] = data
    return data

def build_legend_html(species_to_color: OrderedDict) -> str:
    """Scrollable, resizable legend placed bottom right."""
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
        bottom: 16px;
        right: 16px;
        z-index: 1000;
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
    """Add center marker, main radius, plus 1 km and 5 km rings with labels."""
    # Center point
    folium.CircleMarker([lat, lon], radius=4, color="#2c7fb8", fill=True,
                        fill_opacity=1, tooltip="Center").add_to(m)

    # Main query radius - solid blue
    folium.Circle(
        [lat, lon],
        radius=km_to_m(main_radius_km),
        color="#08519c",
        fill=False,
        weight=3,
        opacity=0.9,
    ).add_to(m)
    folium.Marker([lat, lon + 0.09 * main_radius_km / 10],
                  icon=folium.DivIcon(html=f"<div style='font-size:11px;color:#08519c;'>~{main_radius_km} km</div>")).add_to(m)

    # 1 km ring - dashed black
    folium.Circle(
        [lat, lon],
        radius=km_to_m(1),
        color="#000000",
        fill=False,
        weight=2,
        opacity=0.9,
        dash_array="5,5"
    ).add_to(m)
    folium.Marker([lat, lon + 0.009],
                  icon=folium.DivIcon(html="<div style='font-size:11px;color:#000;'>1 km</div>")).add_to(m)

    # 5 km ring - dashed dark gray
    folium.Circle(
        [lat, lon],
        radius=km_to_m(5),
        color="#555555",
        fill=False,
        weight=2,
        opacity=0.9,
        dash_array="5,7"
    ).add_to(m)
    folium.Marker([lat, lon + 0.045],
                  icon=folium.DivIcon(html="<div style='font-size:11px;color:#555;'>5 km</div>")).add_to(m)

def add_notice(m, text: str):
    """Overlay a centered notice box on the map."""
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

def build_title_html(radius_km: int, back_days: int, ts_display_et: str) -> str:
    """Top title bar with human-readable ET timestamp and archive link."""
    return f"""
      <div style="
          position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
          background: rgba(255,255,255,0.95); padding: 8px 12px; border:1px solid #999;
          border-radius:6px; z-index: 1000; font-size:14px;">
        <div style="font-weight:600;">
          eBird Notable • {radius_km} km radius • last {back_days} day(s)
        </div>
        <div style="display:flex; gap:12px; justify-content:space-between; align-items:center; margin-top:4px; font-size:12px;">
          <span>Built: {ts_display_et}</span>
          <a href="{ARCHIVE_URL}" target="_blank" rel="noopener" style="text-decoration:none;">Archive</a>
        </div>
      </div>
    """

def prune_archive(dirpath: str, keep: int = 30) -> int:
    """Keep the newest N timestamped maps. Do not touch latest.html."""
    try:
        files = [f for f in os.listdir(dirpath)
                 if f.startswith("ebird_radius_map_") and f.endswith(".html")]
        files.sort(reverse=True)  # timestamped names sort correctly
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
    """Save HTML, update latest.html, trigger Colab download if applicable, prune archive."""
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
    # Timestamps: filename uses local system time, display uses America/New_York
    ts_file = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    ts_display_et = datetime.now(ZoneInfo("America/New_York")).strftime("%b %d, %Y %I:%M %p %Z")
    outfile = os.path.join(output_dir, f"ebird_radius_map_{ts_file}_{radius_km}km.html")

    data = get_data(lat, lon, radius_km, back_days)

    # Base map shell
    m = folium.Map(location=[lat, lon], zoom_start=zoom_start, control_scale=True)

    # Title bar: includes timestamp and archive link
    m.get_root().html.add_child(folium.Element(build_title_html(radius_km, back_days, ts_display_et)))

    # Rings and controls
    add_radius_rings(m, lat, lon, radius_km)
    Fullscreen().add_to(m)
    MiniMap(toggle_display=True, position="bottomleft").add_to(m)
    m.add_child(MeasureControl(primary_length_unit="kilometers"))
    LocateControl(auto_start=False, keepCurrentZoomLevel=False).add_to(m)
    MousePosition(separator=" , ", prefix="Lat, Lon:").add_to(m)

    # If no data, still publish an empty map with a clear message
    if not data:
        add_notice(m, "No current notable birds for the selected window.")
        legend_html = build_legend_html(OrderedDict())
        m.get_root().html.add_child(folium.Element(legend_html))
        save_and_publish(m, outfile)
        return m, outfile

    # Build per-location, per-species aggregation
    loc_species = defaultdict(lambda: defaultdict(list))
    species_set = set()
    for s in data:
        slat = s.get("lat")
        slon = s.get("lng")
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

    # Layers and markers
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
                    icon_size=(14, 14),
                    icon_anchor=(7, 7),
                )
                folium.Marker([slat, slon], icon=icon, tooltip=sp,
                              popup=folium.Popup(popup_html, max_width=320)).add_to(species_groups[sp][1])
        folium.LayerControl(collapsed=False).add_to(m)
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
                    icon_size=(14, 14),
                    icon_anchor=(7, 7),
                )
                folium.Marker([slat, slon], icon=icon, tooltip=sp,
                              popup=folium.Popup(popup_html, max_width=320)).add_to(cluster)
        folium.LayerControl(collapsed=False).add_to(m)

    # Legend and publish
    legend_html = build_legend_html(species_to_color)
    m.get_root().html.add_child(folium.Element(legend_html))
    save_and_publish(m, outfile)
    return m, outfile

def show_interactive():
    """Optional notebook controls for radius and back days."""
    if not IN_NOTEBOOK:
        print("Interactive controls only load in a Jupyter or Colab notebook.")
        return
    radius_dd = widgets.Dropdown(options=[2, 5, 10, 15, 20],
                                 value=DEFAULT_RADIUS_KM,
                                 description="Radius (km):",
                                 layout=widgets.Layout(width="250px"))
    back_dd = widgets.Dropdown(options=[1, 2, 3, 5, 7],
                               value=BACK_DAYS,
                               description="Back days:",
                               layout=widgets.Layout(width="250px"))
    out = widgets.Output()

    def _update(*args):
        with out:
            out.clear_output()
            m, outfile = make_map(CENTER_LAT, CENTER_LON,
                                  radius_dd.value, back_dd.value)
            if m:
                display(m)

    radius_dd.observe(_update, names="value")
    back_dd.observe(_update, names="value")
    controls = widgets.HBox([radius_dd, back_dd])
    display(controls)
    _update()

# ---------- One-off render ----------
if __name__ == "__main__":
    m, outfile = make_map(CENTER_LAT, CENTER_LON, DEFAULT_RADIUS_KM, BACK_DAYS)
    if IN_NOTEBOOK and m:
        display(m)
