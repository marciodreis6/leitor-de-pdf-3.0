import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from pallet_control import NFeParser, SEGMENTS


APP_DIR = Path(__file__).resolve().parent
SPREADSHEET_PATH = APP_DIR / "controle_nf_paletes.xlsx"
LOGO_PATH = APP_DIR / "assets" / "mdias_logo_white_transparent.png"
SHEET_NAME = "NF Paletes"
EXPORT_COLUMNS = [
    "Data",
    "NF Palete",
    "Remessa",
    "Segmento",
    "Quantidade",
    "Transportadora",
    "Cliente",
    "Tipo Operação",
    "Chave de Acesso",
]
TEXT_COLUMNS = [
    "Data",
    "NF Palete",
    "Remessa",
    "Segmento",
    "Transportadora",
    "Cliente",
    "Tipo Operação",
    "Chave de Acesso",
]
LOGO_DATA_URI = (
    "data:image/png;base64,"
    + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
)


st.set_page_config(
    page_title="Controle de NF de Paletes",
    page_icon="📦",
    layout="wide",
)


def empty_spreadsheet() -> pd.DataFrame:
    return pd.DataFrame(columns=EXPORT_COLUMNS)


def text_value(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_spreadsheet(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy()
    for column in EXPORT_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    for column in TEXT_COLUMNS:
        normalized[column] = normalized[column].map(text_value).astype("string")
    normalized["Quantidade"] = pd.to_numeric(
        normalized["Quantidade"],
        errors="coerce",
    ).astype("Int64")
    return normalized[EXPORT_COLUMNS]


def load_spreadsheet() -> pd.DataFrame:
    if not SPREADSHEET_PATH.exists():
        return empty_spreadsheet()
    dataframe = pd.read_excel(
        SPREADSHEET_PATH,
        sheet_name=SHEET_NAME,
        dtype={
            "NF Palete": str,
            "Remessa": str,
            "Segmento": str,
            "Chave de Acesso": str,
        },
    )
    return normalize_spreadsheet(dataframe)


def spreadsheet_bytes(dataframe: pd.DataFrame) -> bytes:
    dataframe = normalize_spreadsheet(dataframe)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name=SHEET_NAME)
        worksheet = writer.book[SHEET_NAME]
        widths = {
            "A": 13,
            "B": 13,
            "C": 13,
            "D": 12,
            "E": 12,
            "F": 38,
            "G": 42,
            "H": 18,
            "I": 48,
        }
        for column, width in widths.items():
            worksheet.column_dimensions[column].width = width
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
    return output.getvalue()


def save_spreadsheet(dataframe: pd.DataFrame) -> None:
    SPREADSHEET_PATH.write_bytes(spreadsheet_bytes(dataframe))


def preview_dataframe(results) -> pd.DataFrame:
    rows = []
    for result in results:
        record = result.record
        rows.append(
            {
                "Adicionar": record.identificada_palete,
                "Data": (
                    datetime.strptime(record.data_emissao, "%Y-%m-%d").strftime(
                        "%d/%m/%Y"
                    )
                    if record.data_emissao
                    else ""
                ),
                "NF Palete": record.nf_palete,
                "Remessa": record.remessa,
                "Segmento": record.segmento,
                "Quantidade": record.quantidade_paletes,
                "Transportadora": record.transportadora,
                "Cliente": record.cliente,
                "Tipo Operação": (
                    "Transferência"
                    if record.operacao.startswith("TRANSFER")
                    else "Venda"
                ),
                "Chave de Acesso": record.chave_acesso,
                "Avisos": " | ".join(result.warnings),
            }
        )
    return pd.DataFrame(rows)


def merge_spreadsheet(current: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    combined = normalize_spreadsheet(
        pd.concat([current, new_rows[EXPORT_COLUMNS]], ignore_index=True)
    )
    has_access_key = combined["Chave de Acesso"].fillna("").astype(str).str.strip() != ""
    with_key = combined[has_access_key].drop_duplicates(
        subset=["Chave de Acesso"],
        keep="last",
    )
    without_key = combined[~has_access_key].drop_duplicates(
        subset=["Data", "NF Palete", "Remessa"],
        keep="last",
    )
    combined = pd.concat([with_key, without_key], ignore_index=True)
    combined["_data_ordem"] = pd.to_datetime(
        combined["Data"],
        format="%d/%m/%Y",
        errors="coerce",
    )
    combined = combined.sort_values(
        ["_data_ordem", "NF Palete"],
        ascending=[False, False],
        na_position="last",
    )
    return normalize_spreadsheet(
        combined.drop(columns="_data_ordem").reset_index(drop=True)
    )


def add_to_spreadsheet(selected: pd.DataFrame) -> tuple[int, int, int]:
    current = load_spreadsheet()
    updated = merge_spreadsheet(current, selected)
    save_spreadsheet(updated)
    saved = load_spreadsheet()
    if len(saved) != len(updated):
        raise RuntimeError("A planilha nao foi atualizada corretamente.")
    st.session_state["xml_preview"] = None
    added = max(len(updated) - len(current), 0)
    updated_count = len(selected) - added
    return len(selected), added, updated_count


def clear_all_data() -> None:
    try:
        if SPREADSHEET_PATH.exists():
            SPREADSHEET_PATH.unlink()
    except OSError as exc:
        st.session_state["save_message"] = (
            "error",
            f"Não foi possível apagar a planilha. Feche o arquivo Excel e tente novamente: {exc}",
        )
        return

    upload_version = st.session_state.get("upload_version", 0) + 1
    for key in list(st.session_state):
        del st.session_state[key]
    st.session_state["upload_version"] = upload_version
    st.session_state["save_message"] = (
        "success",
        "Todos os dados foram limpos. A aplicação está pronta para uma nova execução.",
    )


st.markdown(
    """
    <style>
    :root {
        --mdias-bg: #07111c;
        --mdias-bg-grid: #0b1724;
        --mdias-panel: #0c2e4b;
        --mdias-panel-soft: #0d2740;
        --mdias-sidebar: #074575;
        --mdias-line: #245a81;
        --mdias-gold: #f7b917;
        --mdias-blue: #006fb7;
        --mdias-text: #ffffff;
        --mdias-muted: #b7c9db;
    }

    .stApp {
        color: var(--mdias-text);
        background:
            linear-gradient(rgba(11, 23, 36, 0.93), rgba(11, 23, 36, 0.93)),
            linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px),
            linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
            var(--mdias-bg);
        background-size: auto, 72px 72px, 72px 72px, auto;
    }

    .block-container {
        max-width: 1340px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    [data-testid="stHeader"] {
        background: #0b0f15;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, var(--mdias-sidebar), #06385f);
        border-right: 1px solid rgba(255, 255, 255, 0.08);
    }

    [data-testid="stSidebar"] * {
        color: var(--mdias-text);
    }

    .app-hero {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 32px;
        min-height: 140px;
        margin: 0 0 30px;
        padding: 28px 32px;
        border: 1px solid var(--mdias-line);
        border-radius: 8px;
        background: linear-gradient(135deg, #0d3556 0%, #0b2a44 100%);
        box-shadow: 0 18px 45px rgba(0, 0, 0, 0.25);
    }

    .brand-kicker {
        color: var(--mdias-gold);
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        margin-bottom: 12px;
    }

    .app-hero h1 {
        color: var(--mdias-text);
        font-size: clamp(2rem, 3.1vw, 3rem);
        line-height: 1.05;
        margin: 0;
        letter-spacing: 0;
    }

    .subtitle {
        color: #d2e4f6;
        font-size: 1.03rem;
        margin: 14px 0 0;
    }

    .brand-logo {
        display: block;
        width: min(360px, 28vw);
        min-width: 240px;
        height: auto;
        object-fit: contain;
        filter: drop-shadow(0 10px 22px rgba(0, 0, 0, 0.28));
    }

    h2, h3, [data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3 {
        color: var(--mdias-text);
        letter-spacing: 0;
    }

    .stMarkdown p, label, [data-testid="stCaptionContainer"] {
        color: var(--mdias-muted);
    }

    [data-testid="stExpander"] {
        border: 1px solid rgba(80, 127, 165, 0.58);
        border-radius: 8px;
        background: rgba(12, 46, 75, 0.35);
    }

    [data-testid="stFileUploader"] section {
        border: 1px solid rgba(80, 127, 165, 0.7);
        border-radius: 8px;
        background: rgba(12, 46, 75, 0.58);
    }

    [data-testid="stFileUploader"] section:hover {
        border-color: var(--mdias-gold);
    }

    [data-testid="stFileUploader"] button,
    .stButton button,
    .stDownloadButton button {
        min-height: 42px;
        border-radius: 8px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        font-weight: 750;
        letter-spacing: 0;
    }

    .stButton button[kind="primary"],
    .stDownloadButton button[kind="primary"] {
        background: var(--mdias-blue);
        border-color: var(--mdias-blue);
        color: var(--mdias-text);
    }

    .stButton button[kind="primary"]:hover,
    .stDownloadButton button[kind="primary"]:hover {
        background: #087fcf;
        border-color: var(--mdias-gold);
        color: var(--mdias-text);
    }

    .stButton button[kind="secondary"] {
        background: rgba(12, 46, 75, 0.7);
        color: var(--mdias-text);
    }

    .dashboard-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 18px;
        margin: 18px 0 30px;
    }
    .dashboard-card {
        position: relative;
        overflow: hidden;
        min-height: 112px;
        background: linear-gradient(135deg, var(--mdias-panel) 0%, var(--mdias-panel-soft) 100%);
        color: var(--mdias-text);
        border: 1px solid var(--mdias-line);
        border-left: 5px solid var(--mdias-gold);
        border-radius: 8px;
        padding: 22px 24px;
        box-shadow: 0 14px 35px rgba(0, 0, 0, 0.2);
    }
    .dashboard-label {
        color: var(--mdias-gold);
        font-size: 0.78rem;
        font-weight: 850;
        text-transform: uppercase;
        margin-bottom: 18px;
    }
    .dashboard-value {
        color: var(--mdias-text);
        font-size: 2.05rem;
        font-weight: 850;
        line-height: 1;
    }
    .dashboard-helper {
        color: var(--mdias-muted);
        font-size: 0.82rem;
        margin-top: 8px;
    }

    [data-testid="stDataFrame"],
    [data-testid="stDataEditor"] {
        border: 1px solid rgba(80, 127, 165, 0.7);
        border-radius: 8px;
        overflow: hidden;
        background: rgba(8, 13, 21, 0.7);
    }

    [data-testid="stAlert"] {
        border-radius: 8px;
    }

    hr {
        border-color: rgba(255, 255, 255, 0.13);
        margin: 2rem 0;
    }

    @media (max-width: 700px) {
        .block-container {padding-top: 1rem;}
        .app-hero {
            align-items: flex-start;
            flex-direction: column;
            padding: 22px;
        }
        .brand-logo {
            width: min(300px, 78vw);
            min-width: 0;
        }
        .dashboard-grid {grid-template-columns: 1fr;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <section class="app-hero">
        <div>
            <div class="brand-kicker">M. Dias Branco</div>
            <h1>Controle Automatizado de NF de Paletes</h1>
            <p class="subtitle">Importação de XML e atualização da planilha compartilhada.</p>
        </div>
        <img class="brand-logo" src="{LOGO_DATA_URI}" alt="M. Dias Branco">
    </section>
    """,
    unsafe_allow_html=True,
)

save_message = st.session_state.pop("save_message", None)
if save_message:
    message_type, message_text = save_message
    if message_type == "warning":
        st.warning(message_text)
    elif message_type == "error":
        st.error(message_text)
    else:
        st.success(message_text)

with st.expander("Reiniciar aplicação"):
    confirm_clear = st.checkbox(
        "Confirmo que desejo apagar a planilha e limpar todos os dados da tela.",
        key="confirm_clear_all",
    )
    if st.button(
        "Limpar tudo",
        disabled=not confirm_clear,
        type="secondary",
        use_container_width=True,
        on_click=clear_all_data,
    ):
        pass

uploaded_files = st.file_uploader(
    "Selecione um ou mais XMLs de NF-e",
    type=["xml"],
    accept_multiple_files=True,
    key=f"xml_uploader_{st.session_state.get('upload_version', 0)}",
)

if st.button("Processar XMLs", type="primary", disabled=not uploaded_files):
    parser = NFeParser()
    parsed = []
    errors = []
    for uploaded_file in uploaded_files:
        try:
            parsed.append(parser.parse(uploaded_file.getvalue(), uploaded_file.name))
        except Exception as exc:
            errors.append(f"{uploaded_file.name}: {exc}")
    st.session_state["xml_preview"] = preview_dataframe(parsed)
    st.session_state["xml_errors"] = errors

xml_errors = st.session_state.get("xml_errors", [])
invalid_structure_errors = [
    error
    for error in xml_errors
    if "estrutura NF-e valida (infNFe)" in error
]
other_xml_errors = [
    error
    for error in xml_errors
    if error not in invalid_structure_errors
]

if invalid_structure_errors:
    st.caption(
        f"{len(invalid_structure_errors)} arquivo(s) ignorado(s) por não conterem "
        "uma estrutura NF-e válida."
    )
if other_xml_errors:
    with st.expander(f"Outros erros de processamento ({len(other_xml_errors)})"):
        for error in other_xml_errors:
            st.error(error)

preview = st.session_state.get("xml_preview")
if preview is not None and not preview.empty:
    st.subheader("Revisão antes de adicionar")
    edited = st.data_editor(
        preview,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Adicionar": st.column_config.CheckboxColumn(required=True),
            "Segmento": st.column_config.SelectboxColumn(
                options=list(SEGMENTS),
                required=False,
            ),
            "Quantidade": st.column_config.NumberColumn(
                min_value=0,
                step=1,
                format="%d",
            ),
            "Tipo Operação": st.column_config.SelectboxColumn(
                options=["Transferência", "Venda"],
                required=True,
            ),
            "Avisos": st.column_config.TextColumn(disabled=True, width="large"),
            "Chave de Acesso": st.column_config.TextColumn(width="large"),
        },
        disabled=["Avisos"],
        key="xml_editor",
    )

    selected = edited[edited["Adicionar"]].copy()
    add_complete, add_anyway = st.columns(2)
    with add_complete:
        add_complete_clicked = st.button(
            "Adicionar selecionados à planilha",
            type="primary",
            use_container_width=True,
        )
    with add_anyway:
        add_anyway_clicked = st.button(
            "Adicionar assim mesmo",
            use_container_width=True,
        )

    if add_complete_clicked:
        validation_errors = []
        for index, row in selected.iterrows():
            missing = [
                column
                for column in ("Data", "NF Palete", "Remessa", "Segmento", "Quantidade")
                if pd.isna(row.get(column)) or str(row.get(column)).strip() == ""
            ]
            if missing:
                validation_errors.append(
                    f"Linha {index + 1}: preencha {', '.join(missing)}."
                )

        if validation_errors:
            for error in validation_errors:
                st.error(error)
        elif selected.empty:
            st.warning("Selecione ao menos uma linha para adicionar.")
        else:
            processed, added, updated_count = add_to_spreadsheet(selected)
            st.session_state["save_message"] = (
                "success",
                f"{processed} registro(s) processado(s): "
                f"{added} novo(s) e {updated_count} atualizado(s).",
            )
            st.rerun()

    if add_anyway_clicked:
        if selected.empty:
            st.warning("Selecione ao menos uma linha para adicionar.")
        else:
            processed, added, updated_count = add_to_spreadsheet(selected)
            st.session_state["save_message"] = (
                "warning",
                f"{processed} registro(s) processado(s), incluindo incompletos: "
                f"{added} novo(s) e {updated_count} atualizado(s).",
            )
            st.rerun()

st.divider()
st.subheader("Planilha compartilhada")
spreadsheet = load_spreadsheet()

total_pallets = int(
    pd.to_numeric(spreadsheet["Quantidade"], errors="coerce").fillna(0).sum()
)
st.markdown(
    f"""
    <div class="dashboard-grid">
        <div class="dashboard-card">
            <div class="dashboard-label">Notas na planilha</div>
            <div class="dashboard-value">{len(spreadsheet):,}</div>
            <div class="dashboard-helper">Registros disponíveis para consulta</div>
        </div>
        <div class="dashboard-card">
            <div class="dashboard-label">Total de paletes</div>
            <div class="dashboard-value">{total_pallets:,}</div>
            <div class="dashboard-helper">Soma das quantidades identificadas</div>
        </div>
    </div>
    """.replace(",", "."),
    unsafe_allow_html=True,
)

st.dataframe(
    spreadsheet,
    use_container_width=True,
    hide_index=True,
    height=500,
)

st.download_button(
    "Baixar planilha Excel",
    data=spreadsheet_bytes(spreadsheet),
    file_name="controle_nf_paletes.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    disabled=spreadsheet.empty,
    type="primary",
)
