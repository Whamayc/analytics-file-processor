import hashlib
import streamlit as st


def check_password(password: str) -> bool:
    stored = st.secrets.get("APP_PASSWORD_HASH", "")
    if not stored or stored == "sha256_hash_of_your_password_here":
        return False
    return hashlib.sha256(password.encode()).hexdigest() == stored


def render_login() -> None:
    """Render the login form. Calls st.stop() if not authenticated."""
    st.markdown(
        """
        <style>
        .login-wrap { max-width: 360px; margin: 8vh auto 0; }
        .login-title {
            font-family: 'Courier New', monospace;
            font-size: 1.1rem;
            letter-spacing: 0.12em;
            color: #F59E0B;
            text-transform: uppercase;
            margin-bottom: 0.2rem;
        }
        .login-sub {
            font-family: 'Courier New', monospace;
            font-size: 0.72rem;
            color: #525252;
            letter-spacing: 0.08em;
            margin-bottom: 2rem;
        }
        </style>
        <div class="login-wrap">
            <div class="login-title">Analytics File Processor</div>
            <div class="login-sub">EAGLE PACE · MUTUAL FUND ANALYTICS</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_l, col_m, col_r = st.columns([1, 1.4, 1])
    with col_m:
        pwd = st.text_input(
            "Access code",
            type="password",
            label_visibility="collapsed",
            placeholder="Enter access code",
            key="_login_pwd",
        )
        submitted = st.button("Enter", use_container_width=True, type="primary")
        if submitted:
            if check_password(pwd):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid access code.", icon="⛔")


def require_auth() -> None:
    """Call at the top of every page. Blocks if not authenticated."""
    if not st.session_state.get("authenticated", False):
        render_login()
        st.stop()
