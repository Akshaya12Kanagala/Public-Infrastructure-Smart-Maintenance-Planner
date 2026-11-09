import streamlit as st

from core import config, rulebook

st.title("Rulebook")
entries, extras = rulebook.load()
st.caption(f"{len(entries)} runbooks loaded from `{config.rulebook_path().name}`. The system only proposes actions that "
           "come from these entries (no source, no action).")
q = st.text_input("Search the rulebook (symptom, command, service)")
if q:
    hits = rulebook.search_chunks(q, 5)
    if not hits:
        st.warning("No source found for this query.")
    for h in hits:
        with st.expander(f"{h['id']} | {h['section'].title()} | match {h['score']:.2f}", expanded=True):
            st.markdown(h["text"])

tab_rb, tab_extra = st.tabs(["Runbooks", "Rules and lessons"])
with tab_rb:
    for e in entries:
        with st.expander(f"{e.id}: {e.title}"):
            m = e.meta
            c = st.columns(4)
            c[0].markdown(f"**Severity**\n\n{m.get('severity', '-')}")
            c[1].markdown(f"**Approval**\n\n{m.get('approval', '-')}")
            c[2].markdown(f"**Action**\n\n{e.action} (fallback {e.fallback})")
            c[3].markdown(f"**Effort**\n\n~{e.effort_min} min")
            st.markdown(f"**Scope:** {m.get('service scope', '-')}  |  **Resources:** {m.get('resources', '-')}")
            for name in ("trigger", "soft remedy (steps)", "safety limits", "verify", "rollback",
                         "common mishap and fix", "escalate if"):
                if e.sections.get(name, "").strip():
                    st.markdown(f"**{name.title()}**\n{e.sections[name]}")
with tab_extra:
    for title, body in extras:
        with st.expander(title, expanded=title.lower().startswith("global")):
            st.markdown(body)
st.download_button("Download rulebook.md", config.rulebook_path().read_text(encoding="utf-8"), file_name="rulebook.md")
