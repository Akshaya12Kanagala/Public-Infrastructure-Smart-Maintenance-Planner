import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core import charts, config, service, ui
from core.ui_colors import COLORS

st.title("Map & Dependencies")
snap = service.snapshot()
if not ui.require_data(snap):
    st.stop()
t = snap.table.set_index("service")
reg, zones = config.services(), config.registry().get("zones", {})
RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "healthy": 4, "no data": 5}
tab_map, tab_graph = st.tabs(["Asset map", "Dependencies & blast radius"])

with tab_map:
    st.caption("Assets are shown at the logical zone they are assigned to in config/registry.yaml. "
               "The demo itself runs on one host, so zones are labels, while status and urgency are live.")
    m = folium.Map(location=[22.5, 79.0], zoom_start=5, tiles="OpenStreetMap")
    for zone, pos in zones.items():
        members = [s for s, meta in reg.items() if meta.get("zone") == zone and s in t.index]
        if not members:
            continue
        worst = min((t.loc[s, "status"] for s in members), key=lambda s: RANK[s])
        exposure = float(sum(t.loc[s, "exposure_per_min"] for s in members))
        rows = "".join(f"<tr><td>{s}</td><td>{t.loc[s, 'status']}</td><td>{t.loc[s, 'urgency']:.1f}</td></tr>"
                       for s in sorted(members, key=lambda s: -t.loc[s, "urgency"]))
        html = (f"<b>{zone}</b><br>Worst status: <b>{worst}</b><br>Exposure: {ui.money(exposure)}/min"
                f"<table style='font-size:12px'><tr><th>asset</th><th>status</th><th>urgency</th></tr>{rows}</table>")
        folium.CircleMarker([pos["lat"], pos["lon"]], radius=14 + min(18, exposure / 1500), color=COLORS[worst],
                            fill=True, fill_opacity=0.65, popup=folium.Popup(html, max_width=320),
                            tooltip=f"{zone}: {worst}").add_to(m)
    st_folium(m, height=520, width=None, returned_objects=[], key="asset_map")
    zs = pd.DataFrame([{"Zone": z, "Assets": ", ".join(s for s, mt in reg.items() if mt.get("zone") == z),
                        "Worst status": min((t.loc[s, "status"] for s, mt in reg.items() if mt.get("zone") == z and s in t.index),
                                            key=lambda s: RANK[s], default="no data")} for z in zones])
    st.dataframe(zs, hide_index=True, width="stretch")

with tab_graph:
    names = list(reg)
    pick = st.selectbox("If this asset fails, who is affected?", ["(none)"] + names)
    status = {s: t.loc[s, "status"] if s in t.index else "no data" for s in names}
    fig, affected = charts.dependency_graph(status, None if pick == "(none)" else pick)
    st.plotly_chart(fig, width="stretch")
    st.caption("Arrow = 'depends on'. Colour = live status. Red outline = affected if the selected asset fails.")
    if pick != "(none)":
        cost = sum(reg[s]["downtime_cost_per_min"] for s in affected | {pick})
        c1, c2 = st.columns(2)
        c1.metric("Assets in the blast radius", len(affected))
        c2.metric("Downtime cost at risk per minute", ui.money(cost))
        if affected:
            st.dataframe(pd.DataFrame({"Affected asset": sorted(affected),
                                       "Status now": [status[s] for s in sorted(affected)]}), hide_index=True)
