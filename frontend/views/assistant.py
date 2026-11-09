import uuid

import streamlit as st

from core import config, service, ui

st.title("AI Assistant")
if service.mode() == "api":
    st.caption("Answers come from the backend: RAG over the rulebook plus an LLM, with citations.")
else:
    ui.banner("<b>Preview mode:</b> answers are retrieved from the rulebook and the live ranking, without an LLM. "
              "With the backend running (AIOPS_MODE=api) the same page shows LLM answers with citations.", "warn")
st.session_state.setdefault("chat_id", str(uuid.uuid4()))
st.session_state.setdefault("chat", [])

c = st.columns(3)
prompts = ["Which services are at risk right now?", "What should I do when the error rate of a service is high?",
           "How do I handle a memory leak?"]
clicked = None
for col, pr in zip(c, prompts):
    if col.button(pr, width="stretch"):
        clicked = pr

for m in st.session_state["chat"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("citations"):
            with st.expander("Sources"):
                for ci in m["citations"]:
                    st.markdown(f"- {ci.get('type', 'source')}: {ci.get('title', '')}" +
                                (f" (score {ci['score']})" if ci.get("score") else ""))

q = st.chat_input("Ask about risks, incidents or how to fix something") or clicked
if q:
    st.session_state["chat"].append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        with st.spinner("Searching the rulebook and live metrics..."):
            try:
                res = service.answer(q, st.session_state["chat_id"])
            except Exception as e:  # backend or network problem: say so, never invent an answer
                res = {"answer": f"I could not answer: {e}", "citations": []}
        st.markdown(res["answer"])
        if res.get("citations"):
            with st.expander("Sources"):
                for ci in res["citations"]:
                    st.markdown(f"- {ci.get('type', 'source')}: {ci.get('title', '')}")
    st.session_state["chat"].append({"role": "assistant", "content": res["answer"], "citations": res.get("citations", [])})
if st.session_state["chat"] and st.button("Clear conversation"):
    st.session_state["chat"] = []
    st.rerun()
