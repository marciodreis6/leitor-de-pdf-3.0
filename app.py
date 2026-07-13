# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from remessa_parser import dataframe_to_excel_bytes, format_brl, parse_many, summarize


st.set_page_config(page_title="Leitor de Remessas", page_icon="M", layout="wide")


def image_data_uri(path: str) -> str:
    image_path = Path(path)
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


LOGO_DATA_URI = image_data_uri("assets/mdias-branco-logo-transparente.png")


st.markdown(
    """
    <style>
    :root {
        --brand-blue: #003b71;
        --brand-blue-2: #075692;
        --brand-gold: #d8a229;
        --ink: #eaf2fb;
        --text-soft: #a9bdd3;
        --line: rgba(180, 205, 229, .22);
        --panel: #ffffff;
        --surface: #0d1824;
    }

    .stApp {
        background:
            linear-gradient(90deg, rgba(255, 255, 255, .035) 0 1px, transparent 1px 100%),
            linear-gradient(180deg, #111820 0%, #0d1824 44%, #0a1420 100%);
        background-size: 34px 34px, auto;
        color: var(--ink);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, var(--brand-blue) 0%, #062f56 100%);
        border-right: 0;
    }

    [data-testid="stSidebar"] * {
        color: #ffffff !important;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploader"] section {
        background: rgba(255, 255, 255, .08);
        border-color: rgba(255, 255, 255, .28);
        border-radius: 8px;
    }

    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1500px;
    }

    h1, h2, h3, p, label, span {
        letter-spacing: 0;
    }

    .hero {
        border: 1px solid var(--line);
        border-top: 5px solid var(--brand-gold);
        background: linear-gradient(135deg, rgba(8, 33, 57, .98) 0%, rgba(13, 47, 78, .96) 72%, rgba(7, 36, 62, .98) 100%);
        padding: 20px 300px 20px 24px;
        border-radius: 8px;
        margin-bottom: 18px;
        box-shadow: 0 10px 28px rgba(0, 0, 0, .22);
        position: relative;
        overflow: hidden;
    }

    .hero::after {
        display: none;
        content: "";
        position: absolute;
        right: -34px;
        top: -28px;
        width: 190px;
        height: 190px;
        border: 2px solid rgba(216, 162, 41, .45);
        border-radius: 50%;
    }

    .brand-seal {
        position: absolute;
        right: 30px;
        top: 22px;
        display: block;
        background: transparent;
    }

    .brand-logo {
        width: 230px;
        height: auto;
        display: block;
        border-radius: 0;
        box-shadow: none;
    }

    .brand-name {
        color: #d9a93a;
        font-size: .78rem;
        font-weight: 800;
        text-transform: uppercase;
        margin-bottom: 6px;
    }

    .hero-title {
        font-size: 2rem;
        font-weight: 800;
        margin: 0 0 4px 0;
        color: #ffffff;
    }

    .hero-subtitle {
        margin: 0;
        color: var(--text-soft);
        font-size: 1rem;
    }

    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 14px 0 18px 0;
    }

    .kpi {
        border: 1px solid rgba(130, 174, 213, .28);
        border-left: 5px solid var(--brand-gold);
        background: linear-gradient(135deg, rgba(12, 44, 74, .98), rgba(8, 31, 54, .98));
        padding: 16px 18px;
        border-radius: 8px;
        min-height: 96px;
        box-shadow: 0 8px 22px rgba(0, 0, 0, .18);
    }

    .kpi-label {
        color: #d9a93a;
        font-size: .78rem;
        font-weight: 700;
        text-transform: uppercase;
        margin-bottom: 8px;
    }

    .kpi-value {
        font-size: 1.55rem;
        font-weight: 800;
        white-space: nowrap;
        color: #ffffff;
    }

    .section-title {
        margin: 24px 0 10px 0;
        font-size: 1.05rem;
        font-weight: 800;
        color: #ffffff;
    }

    .hint {
        color: var(--text-soft);
        font-size: .9rem;
        margin-top: -2px;
    }

    .empty-state {
        color: var(--text-soft);
        font-size: .92rem;
        margin-top: 8px;
        padding: 14px 0;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 10px 28px rgba(0, 0, 0, .22);
    }

    .stDownloadButton button, .stButton button {
        border-radius: 8px;
        border: 1px solid var(--brand-blue);
        background: var(--brand-blue);
        color: #ffffff;
        font-weight: 800;
        min-height: 34px;
        padding: 4px 18px;
    }

    .stDownloadButton button:hover, .stButton button:hover {
        border-color: #002f5a;
        background: #002f5a;
        color: #ffffff;
    }

    div[data-testid="stAlert"] {
        width: fit-content;
        max-width: min(560px, 100%);
        border-radius: 8px;
        padding: 0;
        margin: 8px 0 18px 0;
    }

    div[data-testid="stAlert"] > div {
        padding: 8px 14px;
    }

    div[data-testid="stAlert"] p {
        font-size: .86rem;
        margin: 0;
    }

    div.stDownloadButton {
        width: fit-content;
        margin-top: 12px;
    }

    @media (max-width: 900px) {
        .kpi-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .kpi-value {
            font-size: 1.2rem;
        }
        .brand-seal {
            display: none;
        }
        .hero {
            padding-right: 24px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


st.markdown(
    f"""
    <div class="hero">
        <div class="brand-name">M. Dias Branco</div>
        <div class="hero-title">Leitor de Remessas</div>
        <p class="hero-subtitle">Manifestos PDF para planilha de cargas pendentes.</p>
        <div class="brand-seal">
            <img class="brand-logo" src="{LOGO_DATA_URI}" alt="M. Dias Branco">
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.header("Arquivos")
    uploaded_files = st.file_uploader(
        "Envie um ou mais PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )
    st.divider()
    st.caption("Faturamento - 432")
    st.caption("Horario: America/Sao_Paulo")


if not uploaded_files:
    st.markdown('<div class="empty-state">Aguardando PDF.</div>', unsafe_allow_html=True)
    st.stop()


files_for_parser = []
for uploaded_file in uploaded_files:
    files_for_parser.append((uploaded_file.name, BytesIO(uploaded_file.getvalue())))

with st.spinner("Lendo manifestos e validando campos..."):
    result = parse_many(files_for_parser)

df = result.dataframe

if df.empty:
    st.warning("Nenhuma remessa valida foi encontrada nos PDFs enviados.")
    st.stop()

summary = summarize(df)
st.markdown(
    f"""
    <div class="kpi-grid">
        <div class="kpi">
            <div class="kpi-label">Remessas</div>
            <div class="kpi-value">{int(summary["remessas"])}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Valor total</div>
            <div class="kpi-value">R$ {format_brl(summary["valor"])}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Peso total</div>
            <div class="kpi-value">{format_brl(summary["peso"])} kg</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Volumes</div>
            <div class="kpi-value">{int(summary["volume"]):,}</div>
        </div>
    </div>
    """.replace(",", "."),
    unsafe_allow_html=True,
)

if result.issues:
    with st.expander(f"Alertas ({len(result.issues)})", expanded=True):
        issue_df = pd.DataFrame([issue.__dict__ for issue in result.issues])
        st.dataframe(issue_df, use_container_width=True, hide_index=True)

st.markdown('<div class="section-title">Resultado para colar ou baixar</div>', unsafe_allow_html=True)
st.markdown('<div class="hint">Revise antes de baixar.</div>', unsafe_allow_html=True)

edited_df = st.data_editor(
    df,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "PESO": st.column_config.TextColumn("PESO"),
        "VALOR": st.column_config.TextColumn("VALOR"),
        "VOLUME": st.column_config.TextColumn("VOLUME"),
        "NOVA AGENDA": st.column_config.TextColumn("NOVA AGENDA"),
    },
)

download_name = f"prefat_{datetime.now().strftime('%d-%m-%Y_%H-%M')}.xlsx"
excel_bytes = dataframe_to_excel_bytes(edited_df)

st.download_button(
    "Baixar XLSX",
    data=excel_bytes,
    file_name=download_name,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=False,
)
