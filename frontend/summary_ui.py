"""Özet sonucunu sunan tekrar kullanılabilir Streamlit bileşenleri."""

import html
import json

import streamlit as st
import streamlit.components.v1 as components


def render_summary_section(title: str, content: str | list[str], variant: str = "") -> None:
    items = content if isinstance(content, list) else []
    if (isinstance(content, list) and not items) or (
        isinstance(content, str) and not content.strip()
    ):
        return
    if items:
        body = "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"
    else:
        body = f"<p>{html.escape(content)}</p>"
    st.markdown(
        f'<div class="sd-detail-block"><p class="sd-detail-title {variant}">{title}</p>'
        f'<div class="sd-detail-body">{body}</div></div>',
        unsafe_allow_html=True,
    )


def copy_summary_button(summary: str) -> None:
    """Tarayıcı panosuna kopyalayan, metinsiz küçük bir düğme gösterir."""
    safe_summary = json.dumps(summary).replace("<", "\\u003c")
    components.html(
        f"""
        <style>
          html, body {{ margin:0; background:transparent; font-family:'Inter',system-ui,sans-serif; }}
          button {{ width:100%; height:38px; border:1px solid rgba(255,255,255,.16); border-radius:9px;
                   background:#111116; color:#f5f5f7; cursor:pointer; font-size:16px; }}
          button:hover {{ background:#17171f; border-color:#34d399; }}
        </style>
        <button id="copy" title="Özeti kopyala" aria-label="Özeti kopyala">⧉</button>
        <script>
          const summary = {safe_summary};
          const button = document.getElementById('copy');
          button.addEventListener('click', async () => {{
            try {{
              await navigator.clipboard.writeText(summary);
            }} catch (error) {{
              const area = document.createElement('textarea');
              area.value = summary;
              document.body.appendChild(area);
              area.select();
              document.execCommand('copy');
              area.remove();
            }}
            button.textContent = '✓';
            setTimeout(() => button.textContent = '⧉', 1500);
          }});
        </script>
        """,
        height=40,
    )
