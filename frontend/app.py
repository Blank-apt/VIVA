"""
Viva — Adaptive Interview & Viva Prep Coach, Streamlit frontend.

A thin client over the Part C FastAPI backend. This file makes no direct
database or LLM calls of its own — every piece of state (mastery, session
history, question text, evaluation) comes from the backend's HTTP API,
exactly as a real browser frontend would consume it.

Run:
    cd frontend
    streamlit run app.py

Requires the backend running separately (see backend/README.md):
    cd backend/part_c
    uvicorn main:app --reload
"""
from __future__ import annotations

import uuid
from datetime import datetime

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Page setup + a small amount of injected type/color polish beyond Streamlit's
# base theme (config.toml sets the palette; this adds the display face for
# headings, since Streamlit's theme.font only accepts sans-serif/serif/mono).
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Viva — Adaptive Interview Coach",
    page_icon="🎓",
    layout="wide",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@500;700&display=swap');
    h1, h2, h3, .viva-wordmark { font-family: 'Fraunces', Georgia, serif; }
    .viva-wordmark { font-size: 2.1rem; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 0; }
    .viva-tagline { color: #5B6472; font-size: 1.0rem; margin-top: -0.3rem; margin-bottom: 1.6rem; }
    .viva-badge {
        display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; letter-spacing: 0.02em;
    }
    .viva-badge-foundational { background: #E7EEFA; color: #2B4C8C; }
    .viva-badge-medium { background: #FBF1DC; color: #8C6A1B; }
    .viva-badge-edge_cases { background: #FBE7E4; color: #A13A2A; }
    .viva-qcard {
        border: 1px solid #E3E7EE; border-radius: 10px; padding: 1.1rem 1.3rem;
        background: #FBFBFC; margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "session_id" not in st.session_state:
    st.session_state.session_id = f"streamlit-{uuid.uuid4().hex[:10]}"
if "backend_url" not in st.session_state:
    st.session_state.backend_url = "http://127.0.0.1:8000"
if "current_question" not in st.session_state:
    st.session_state.current_question = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "session_ended" not in st.session_state:
    st.session_state.session_ended = False


# ---------------------------------------------------------------------------
# Thin API client — every network call funnels through here so error
# handling (backend down, bad request, etc.) is consistent everywhere.
# ---------------------------------------------------------------------------
def _base_url() -> str:
    return st.session_state.backend_url.rstrip("/")


def api_get(path: str):
    try:
        resp = requests.get(f"{_base_url()}{path}", timeout=30)
    except requests.exceptions.ConnectionError:
        return None, "Can't reach the backend. Is `uvicorn main:app` running?"
    except requests.exceptions.Timeout:
        return None, "Backend timed out."
    if resp.status_code >= 400:
        return None, _extract_error(resp)
    return resp.json(), None


def api_post(path: str, payload: dict):
    try:
        resp = requests.post(f"{_base_url()}{path}", json=payload, timeout=60)
    except requests.exceptions.ConnectionError:
        return None, "Can't reach the backend. Is `uvicorn main:app` running?"
    except requests.exceptions.Timeout:
        return None, "Backend timed out — the LLM call may be slow or rate-limited."
    if resp.status_code >= 400:
        return None, _extract_error(resp)
    return resp.json(), None


def _extract_error(resp: requests.Response) -> str:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    return f"[{resp.status_code}] {detail}"


def difficulty_badge(difficulty: str | None) -> str:
    if not difficulty:
        return ""
    label = difficulty.replace("_", " ").title()
    return f'<span class="viva-badge viva-badge-{difficulty}">{label}</span>'


# ---------------------------------------------------------------------------
# Sidebar — connection, mode, session lifecycle
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Connection")
    st.session_state.backend_url = st.text_input(
        "Backend URL", value=st.session_state.backend_url
    )

    health, err = api_get("/health")
    if health:
        st.success("Backend reachable", icon="✅")
    else:
        st.error(err or "Backend unreachable", icon="🚫")

    st.markdown("---")
    st.markdown("### Session")
    st.caption(f"`{st.session_state.session_id}`")

    if st.button("🔄 New session", use_container_width=True):
        st.session_state.session_id = f"streamlit-{uuid.uuid4().hex[:10]}"
        st.session_state.current_question = None
        st.session_state.last_result = None
        st.session_state.session_ended = False
        st.rerun()

    summary_text = st.text_input("Session summary (optional)", key="summary_input")
    if st.button("🏁 End session", use_container_width=True, disabled=st.session_state.session_ended):
        result, err = api_post(
            "/interview/end-session",
            {"session_id": st.session_state.session_id, "summary": summary_text or None},
        )
        if err:
            st.error(err)
        else:
            st.session_state.session_ended = True
            st.success(f"Session ended (backend id {result['session_id']}).")

    st.markdown("---")
    mode = st.selectbox(
        "Interview mode",
        options=["fundamentals", "scenario", "your-projects"],
        format_func=lambda m: {
            "fundamentals": "Fundamentals (DSA / OS / DBMS)",
            "scenario": "Scenario / System Design",
            "your-projects": "Your Projects",
        }[m],
    )

    topic_choice = st.text_input(
        "Specific topic (optional — leave blank to auto-pick your weakest)",
        key="topic_input",
    )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown('<p class="viva-wordmark">Viva</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="viva-tagline">Adaptive interview &amp; viva prep — it remembers what you struggle with.</p>',
    unsafe_allow_html=True,
)

col_main, col_side = st.columns([2, 1], gap="large")

# ---------------------------------------------------------------------------
# Main column — the interview loop itself
# ---------------------------------------------------------------------------
with col_main:
    st.markdown("#### Interview")

    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        get_question_clicked = st.button("▶ Get next question", use_container_width=True, type="primary")
    with btn_col2:
        clear_clicked = st.button("✕ Clear current question", use_container_width=True)

    if clear_clicked:
        st.session_state.current_question = None
        st.session_state.last_result = None
        st.rerun()

    if get_question_clicked:
        payload = {
            "session_id": st.session_state.session_id,
            "mode": mode,
            "topic": topic_choice or None,
        }
        with st.spinner("Asking the interviewer for a question…"):
            question, err = api_post("/interview/next-question", payload)
        if err:
            st.error(err)
        else:
            st.session_state.current_question = question
            st.session_state.last_result = None

    question = st.session_state.current_question

    if question is None:
        st.info("Click **Get next question** to start.")
    else:
        st.markdown(
            f"""
            <div class="viva-qcard">
                {difficulty_badge(question.get("difficulty"))}
                &nbsp;<b>{question["topic"]}</b> · <span style="color:#5B6472">{question["mode"]}</span>
                <p style="margin-top:0.6rem; margin-bottom:0; font-size:1.05rem;">{question["question_text"]}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if question.get("checklist"):
            with st.expander("Grading checklist (scenario/project mode)"):
                for item in question["checklist"]:
                    st.markdown(f"- {item}")

        answer_text = st.text_area(
            "Your answer",
            height=160,
            placeholder="Type your answer as if you were speaking it in the interview…",
            key=f"answer_{question['question_id']}",
        )

        if st.button("✔ Submit answer", type="primary"):
            if not answer_text.strip():
                st.warning("Write an answer first.")
            else:
                payload = {
                    "session_id": st.session_state.session_id,
                    "question_id": question["question_id"],
                    "transcript_override": answer_text.strip(),
                }
                with st.spinner("Evaluating your answer…"):
                    result, err = api_post("/interview/submit-answer", payload)
                if err:
                    st.error(err)
                else:
                    st.session_state.last_result = result
                    st.session_state.current_question = None
                    st.rerun()

    result = st.session_state.last_result
    if result:
        st.markdown("#### Result")
        score = result["evaluation"]["score"]
        r1, r2, r3 = st.columns(3)
        r1.metric("Score", f"{score:.0%}")
        r2.metric(
            "Points",
            f"{result['evaluation']['points_earned']} / {result['evaluation']['points_possible']}",
        )
        r3.markdown(
            f"**Next difficulty for this topic**<br>{difficulty_badge(result.get('next_difficulty'))}",
            unsafe_allow_html=True,
        )
        st.progress(min(max(score, 0.0), 1.0))
        st.markdown(f"**Transcript graded:** _{result['transcript']}_")
        st.markdown(f"**Feedback:** {result['evaluation']['rationale']}")

        detail = result["evaluation"].get("detail", {})
        missed = detail.get("missed_concepts")
        if missed:
            st.markdown("**Missed concepts:**")
            for m in missed:
                st.markdown(f"- {m}")

# ---------------------------------------------------------------------------
# Side column — mastery dashboard + session history
# ---------------------------------------------------------------------------
with col_side:
    st.markdown("#### Mastery — " + {
        "fundamentals": "Fundamentals",
        "scenario": "Scenario",
        "your-projects": "Your Projects",
    }[mode])

    mastery, err = api_get(f"/mastery/{mode}")
    if err:
        st.error(err)
    elif mastery:
        chart_data = {row["topic"]: row["score"] for row in mastery}
        st.bar_chart(chart_data, height=420)
        weakest = mastery[0]
        st.caption(
            f"Weakest right now: **{weakest['topic']}** "
            f"({weakest['score']:.2f}, {weakest['difficulty'].replace('_', ' ')})"
        )
    else:
        st.info("No mastery data yet.")

    st.markdown("---")
    st.markdown("#### Session history")
    history, err = api_get(f"/interview/session/{st.session_state.session_id}")
    if err:
        st.caption("No questions answered yet this session.")
    elif history:
        if history.get("summary"):
            st.caption(f"Summary: {history['summary']}")
        for row in reversed(history["qa"]):
            score_str = f"{row['score']:.0%}" if row["score"] is not None else "—"
            with st.expander(f"{row['topic']} · {score_str} · {row['difficulty'] or '—'}"):
                st.markdown(f"**Q:** {row['question']}")
                st.markdown(f"**A:** {row['transcript']}")
                st.caption(row["created_at"])
