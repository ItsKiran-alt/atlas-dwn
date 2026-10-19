"""Atlas Wealth Management: Dynamic Wealth Navigator (Streamlit entry point).

Every UI event runs in ONE database transaction (commit on success, roll back on error). All permission checks
happen in dwn.services on the server; the browser component only renders HTML and forwards user actions.
"""
import logging
import os
import uuid
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Community Cloud keeps secrets in st.secrets; our config reads environment variables, so copy top-level text secrets across (never overwriting real env vars).
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float, bool)) and _k not in os.environ:
            os.environ[_k] = str(_v)
except Exception:          # no secrets file (local development): environment variables only
    pass

from dwn import bootstrap
from dwn.db.session import session_scope
from dwn.repo import Repo
from dwn.ui import controller

log = logging.getLogger("dwn")

st.set_page_config(page_title="Atlas Wealth Management — RM Workbench", page_icon="◆", layout="wide", initial_sidebar_state="collapsed")

# Hide Streamlit chrome and let the component fill the viewport so the original sticky header/sidebar behave as designed.
st.markdown("""<style>
header[data-testid="stHeader"],div[data-testid="stToolbar"],div[data-testid="stDecoration"],footer,#MainMenu{display:none!important}
.stApp,.block-container{padding:0!important;margin:0!important;max-width:100%!important;background:#f4f7fb}
div[data-testid="stCustomComponentV1"],iframe[title*="atlas_ui"]{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;border:0!important;z-index:999999}
</style>""", unsafe_allow_html=True)

_component = components.declare_component("atlas_ui", path=str(Path(__file__).parent / "ui_component"))


@st.cache_resource(show_spinner=False)
def _init_db() -> bool:
    bootstrap.init()          # validate config, run migrations, seed synthetic demo data once (never by default in production)
    return True


try:
    _init_db()
except Exception:
    ref = uuid.uuid4().hex[:8]
    log.exception("start-up failed (ref %s)", ref)
    st.error(f"The service could not start. Please contact the administrator and quote reference {ref}.")
    st.stop()

if "sess" not in st.session_state:
    st.session_state["sess"] = controller.new_session()
sess = st.session_state["sess"]

try:
    with session_scope() as db:
        repo = Repo(db)
        ev = st.session_state.get("atlas")
        if isinstance(ev, dict) and ev.get("id") and ev["id"] != sess.get("last_event"):
            sess["last_event"] = ev["id"]
            controller.handle(repo, sess, ev)
        payload = controller.build(repo, sess)
except Exception:
    ref = uuid.uuid4().hex[:8]
    log.exception("page build failed (ref %s)", ref)                 # details stay in the server log; the browser only gets a reference
    st.error(f"Something went wrong loading this page. Nothing was changed. Reference {ref}.")
    st.stop()

_component(key="atlas", default=None, **payload)
