from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import re
from typing import BinaryIO, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import pdfplumber


OUTPUT_COLUMNS = [
    "PRÉ-FAT",
    "REMESSA",
    "TRANSPORTADORA",
    "SEGMENTO",
    "NOVA AGENDA",
    "PESO",
    "VALOR",
    "VOLUME",
    "CLIENTE",
    "LOCAL DE ENTREGA",
    "NF",
    "DATA",
    "HORA",
]

EXPORT_CLIENT_BY_CARRIER = {
    "J W SOLUCOES INTEGRADAS": "WADI BAILOOL GENERAL TRADING CO.",
    "MMA": "TRANSNATIONAL FOODS",
}

CARRIER_ALIASES = {
    "M DIAS BRANCO": "M DIAS BRANCO S.A.",
}

CLIENT_ALIASES = {
    "AMERICANAS": "AMERICANAS RECUPERACAO",
    "ATAKAREJO DISTRIBUIDOR": "ATAKAREJO DISTRIBUIDOR",
    "MACAM COMERCIO ATACADISTA": "MACAM COMERCIO ATACADISTA",
    "MIX ATACADISTA": "MIX ATACADISTA",
    "NOVO ATACADO": "NOVO MIX ATACADO",
    "NOVO MIX ATACADO": "NOVO MIX ATACADO",
}


@dataclass(frozen=True)
class ParseIssue:
    arquivo: str
    remessa: str
    campo: str
    detalhe: str


@dataclass(frozen=True)
class ParseResult:
    dataframe: pd.DataFrame
    issues: list[ParseIssue]


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_key(value: str) -> str:
    replacements = str.maketrans(
        {
            "Á": "A",
            "À": "A",
            "Â": "A",
            "Ã": "A",
            "É": "E",
            "Ê": "E",
            "Í": "I",
            "Ó": "O",
            "Ô": "O",
            "Õ": "O",
            "Ú": "U",
            "Ç": "C",
        }
    )
    return normalize_spaces(value).upper().translate(replacements)


def clean_name(name: str, max_words: int | None = None) -> str:
    name = normalize_spaces(name)
    name = re.sub(r"\s*\d+$", "", name)
    words = []

    for index, word in enumerate(name.split()):
        word = word.strip(".,;:/\\|-")
        if not word:
            continue
        if any(char.isdigit() for char in word):
            continue
        if len(word) > 3 or (index == 0 and 1 <= len(word) <= 3):
            words.append(word)

    if max_words:
        words = words[:max_words]
    return " ".join(words)


def parse_number(value: str) -> float:
    if value is None or value == "":
        return 0.0
    return float(value.replace(".", "").replace(",", "."))


def format_brl(value: float) -> str:
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def extract_text_from_pdf(file: str | BinaryIO | BytesIO) -> str:
    chunks: list[str] = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            chunks.append(text)
    return "\n".join(chunks)


def split_manifest_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"(?=Relat[oó]rio de Manifesto de Carga)", text, flags=re.IGNORECASE)
    return [block.strip() for block in blocks if re.search(r"Nro\s+Remessa|Remessa", block, re.IGNORECASE)]


def extract_remessa(block: str) -> str:
    match = re.search(r"(?:Nro\s*)?Remessa:\s*0*(\d+)", block, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def extract_transportadora(block: str) -> str:
    match = re.search(
        r"Transportador[a]?:\s*(.*?)(?:\s+Impresso\s+por:|\s+Impresso|$)",
        block,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    carrier = clean_name(match.group(1), max_words=7)
    carrier_key = normalize_key(carrier)
    for key, alias in CARRIER_ALIASES.items():
        if normalize_key(key) in carrier_key:
            return alias
    return carrier


def extract_total(block: str) -> tuple[str, str, str]:
    match = re.search(
        r"Total\s+Geral:\s*(\d+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        block,
        flags=re.IGNORECASE,
    )
    if not match:
        return "", "", ""
    volume, _peso_liquido, peso_bruto, valor = match.groups()
    return volume, peso_bruto, valor


def extract_cities(block: str) -> str:
    match = re.search(r"Cidade:\s*(.*?)(?:\nInformações|\nTotal|\n\*{3,}|$)", block, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    cities = [normalize_spaces(line) for line in match.group(1).splitlines()]
    cities = [city for city in cities if city]
    return "/".join(dict.fromkeys(cities))


def extract_nfs(block: str) -> str:
    nfs: list[str] = []
    for line in block.splitlines():
        match = re.match(r"\s*\d{3,5}\s+(\d{6,})\b", line)
        if match:
            nf = match.group(1).lstrip("0")
            nfs.append(nf)

    if not nfs:
        for nf in re.findall(r"\b\d{6,}\b", block):
            clean_nf = nf.lstrip("0")
            if clean_nf.startswith(("11", "12", "16")):
                nfs.append(clean_nf)

    unique = sorted(set(nfs), key=lambda value: int(value))
    if not unique:
        return ""
    return f"{unique[0]} a {unique[-1]}" if len(unique) > 1 else unique[0]


def extract_clients(block: str) -> list[str]:
    clients: list[str] = []
    lines = block.splitlines()

    for index, line in enumerate(lines):
        if not re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", line):
            continue

        after_doc = re.split(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", line, maxsplit=1)[-1]
        name_part = re.split(r"\s+\d{1,3}(?:\.\d{3})*,\d{3}\b", after_doc, maxsplit=1)[0]

        continuation = []
        for next_line in lines[index + 1 : index + 3]:
            if re.search(r"Total\s+Geral|Cidade:|^\s*\d{3,5}\s+\d{6,}", next_line, flags=re.IGNORECASE):
                break
            if re.search(r"\d{1,3}(?:\.\d{3})*,\d{3}", next_line):
                break
            continuation.append(next_line)

        cleaned = clean_name(" ".join([name_part, *continuation]), max_words=4)
        client_key = normalize_key(cleaned)
        for key, alias in CLIENT_ALIASES.items():
            if normalize_key(key) in client_key:
                cleaned = alias
                break
        if cleaned:
            clients.append(cleaned)

    return list(dict.fromkeys(clients))


def resolve_client(block: str, transportadora: str) -> str:
    carrier_key = normalize_key(transportadora)
    for key, fixed_client in EXPORT_CLIENT_BY_CARRIER.items():
        if normalize_key(key) in carrier_key:
            return fixed_client

    clients = extract_clients(block)
    if len(clients) > 1:
        return "DIVERSOS"
    return clients[0] if clients else ""


def collect_issues(row: dict[str, str], arquivo: str) -> Iterable[ParseIssue]:
    required_fields = ["REMESSA", "TRANSPORTADORA", "PESO", "VALOR", "VOLUME", "CLIENTE", "LOCAL DE ENTREGA", "NF"]
    for field in required_fields:
        if not row.get(field):
            yield ParseIssue(arquivo=arquivo, remessa=row.get("REMESSA", ""), campo=field, detalhe="Campo nao encontrado no PDF.")


def parse_pdf(file: str | BinaryIO | BytesIO, filename: str = "arquivo.pdf") -> ParseResult:
    text = extract_text_from_pdf(file)
    blocks = split_manifest_blocks(text)
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    rows: list[dict[str, str]] = []
    issues: list[ParseIssue] = []

    for block in blocks:
        remessa = extract_remessa(block)
        transportadora = extract_transportadora(block)
        volume, peso, valor = extract_total(block)
        if not (volume or peso or valor):
            continue

        row = {
            "PRÉ-FAT": "PRÉ-FAT",
            "REMESSA": remessa,
            "TRANSPORTADORA": transportadora,
            "SEGMENTO": "",
            "NOVA AGENDA": "",
            "PESO": peso,
            "VALOR": valor,
            "VOLUME": volume,
            "CLIENTE": resolve_client(block, transportadora),
            "LOCAL DE ENTREGA": extract_cities(block),
            "NF": extract_nfs(block),
            "DATA": now.strftime("%d/%m/%Y"),
            "HORA": now.strftime("%H:%M:%S"),
        }
        rows.append(row)
        issues.extend(collect_issues(row, filename))

    dataframe = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    return ParseResult(dataframe=dataframe, issues=issues)


def parse_many(files: Iterable[tuple[str, BinaryIO | BytesIO | str]]) -> ParseResult:
    frames: list[pd.DataFrame] = []
    issues: list[ParseIssue] = []

    for filename, file in files:
        result = parse_pdf(file, filename=filename)
        if not result.dataframe.empty:
            frames.append(result.dataframe)
        issues.extend(result.issues)

    if frames:
        dataframe = pd.concat(frames, ignore_index=True)
        dataframe = sort_dataframe(dataframe)
    else:
        dataframe = pd.DataFrame(columns=OUTPUT_COLUMNS)

    return ParseResult(dataframe=dataframe, issues=issues)


def sort_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe
    df = dataframe.copy()
    df["_cliente_order"] = df["CLIENTE"].str.upper().eq("DIVERSOS").astype(int)
    df["_cliente_sort"] = df["CLIENTE"].str.upper()
    df["_remessa_sort"] = pd.to_numeric(df["REMESSA"], errors="coerce")
    df = df.sort_values(["_cliente_order", "_cliente_sort", "_remessa_sort"], na_position="last")
    return df.drop(columns=["_cliente_order", "_cliente_sort", "_remessa_sort"]).reset_index(drop=True)


def summarize(dataframe: pd.DataFrame) -> dict[str, float]:
    if dataframe.empty:
        return {"remessas": 0, "valor": 0.0, "peso": 0.0, "volume": 0.0}

    return {
        "remessas": float(len(dataframe)),
        "valor": dataframe["VALOR"].map(parse_number).sum(),
        "peso": dataframe["PESO"].map(parse_number).sum(),
        "volume": pd.to_numeric(dataframe["VOLUME"], errors="coerce").fillna(0).sum(),
    }


def dataframe_to_excel_bytes(dataframe: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Cargas Pendentes")
        worksheet = writer.sheets["Cargas Pendentes"]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        widths = {
            "A": 12,
            "B": 12,
            "C": 34,
            "D": 16,
            "E": 16,
            "F": 14,
            "G": 14,
            "H": 12,
            "I": 34,
            "J": 24,
            "K": 20,
            "L": 12,
            "M": 12,
        }
        for column, width in widths.items():
            worksheet.column_dimensions[column].width = width
    return output.getvalue()
