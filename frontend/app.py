"""Smart Maintenance Planner: Streamlit control room. Run:  streamlit run app.py"""
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Smart Maintenance Planner", page_icon=":material/engineering:", layout="wide")

from core import service, ui  # noqa: E402  (after set_page_config)

ui.inject_css()
snap = service.snapshot()
ui.sidebar(snap)

nav = st.navigation({
    "Operate": [
        st.Page("views/command_center.py", title="Command Center", icon=":material/dashboard:", default=True),
        st.Page("views/risk_ranking.py", title="Risk Ranking", icon=":material/priority_high:"),
        st.Page("views/asset_detail.py", title="Asset Detail", icon=":material/monitoring:"),
        st.Page("views/incidents.py", title="Incidents", icon=":material/warning:"),
        st.Page("views/work_orders.py", title="Work Orders", icon=":material/assignment:"),
    ],
    "Understand": [
        st.Page("views/map_graph.py", title="Map & Dependencies", icon=":material/hub:"),
        st.Page("views/assistant.py", title="AI Assistant", icon=":material/smart_toy:"),
        st.Page("views/rulebook_page.py", title="Rulebook", icon=":material/menu_book:"),
    ],
    "Prove & Govern": [
        st.Page("views/scenario_lab.py", title="Scenario Lab", icon=":material/science:"),
        st.Page("views/success_metrics.py", title="Success Metrics", icon=":material/trending_up:"),
        st.Page("views/governance.py", title="Guardrails & Settings", icon=":material/shield:"),
    ],
})
nav.run()
