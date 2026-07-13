from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET

import pandas as pd


SEGMENTS = ("31M", "31F", "432", "PALETE")
GMA_CNPJ = "07206816003050"
FILIAL_432_CNPJ = "07206816005770"
OPERATIONS = ("TRANSFERÊNCIA", "VENDA")


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().upper()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def first_text(root: ET.Element, name: str) -> str:
    for element in root.iter():
        if local_name(element.tag) == name and element.text:
            return element.text.strip()
    return ""


def section_text(root: ET.Element, section: str, field: str) -> str:
    for element in root.iter():
        if local_name(element.tag) != section:
            continue
        for child in element.iter():
            if local_name(child.tag) == field and child.text:
                return child.text.strip()
    return ""


def all_xml_text(root: ET.Element) -> str:
    values = [element.text.strip() for element in root.iter() if element.text and element.text.strip()]
    return " ".join(values)


def integer_quantity(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value.replace(",", ".")))
    except ValueError:
        return None


def find_labeled_value(text: str, labels: tuple[str, ...], value_pattern: str) -> str:
    normalized = normalize_text(text)
    label_pattern = "|".join(re.escape(normalize_text(label)) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})\s*(?:N[Oº.]*)?\s*[:#=\-]?\s*({value_pattern})",
        normalized,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


@dataclass
class PalletRecord:
    nf_palete: str
    remessa: str
    segmento: str
    transportadora: str
    cliente: str
    operacao: str
    uf_cliente: str
    quantidade_paletes: int | None
    chave_acesso: str
    emitente: str
    data_emissao: str
    identificada_palete: bool
    motivo_identificacao: str
    arquivo_origem: str
    xml_original: str


@dataclass
class ParseResult:
    record: PalletRecord
    warnings: list[str]


class NFeParser:
    def __init__(self, pallet_keywords: tuple[str, ...] = ("PALETE", "PALLET")):
        self.pallet_keywords = tuple(normalize_text(keyword) for keyword in pallet_keywords)

    def parse(self, xml_content: bytes | str, filename: str = "") -> ParseResult:
        if isinstance(xml_content, bytes):
            xml_text = xml_content.decode("utf-8-sig", errors="replace")
        else:
            xml_text = xml_content

        root = ET.fromstring(xml_text)
        inf_nfe = next(
            (element for element in root.iter() if local_name(element.tag) == "infNFe"),
            None,
        )
        if inf_nfe is None:
            raise ValueError("O arquivo nao contem uma estrutura NF-e valida (infNFe).")

        access_key = inf_nfe.attrib.get("Id", "")
        access_key = re.sub(r"\D", "", access_key)
        if not access_key:
            access_key = re.sub(r"\D", "", first_text(root, "chNFe"))

        nf_number = section_text(root, "ide", "nNF")
        recipient_name = section_text(root, "dest", "xNome")
        recipient_cnpj = re.sub(r"\D", "", section_text(root, "dest", "CNPJ"))
        recipient_uf = section_text(root, "dest", "UF").upper()
        recipient_city = section_text(root, "dest", "xMun")
        issuer_name = section_text(root, "emit", "xNome")
        issuer_cnpj = re.sub(r"\D", "", section_text(root, "emit", "CNPJ"))
        carrier_name = section_text(root, "transporta", "xNome")
        issue_date = section_text(root, "ide", "dhEmi") or section_text(root, "ide", "dEmi")
        nature = section_text(root, "ide", "natOp")
        product_names = [
            element.text.strip()
            for element in root.iter()
            if local_name(element.tag) == "xProd" and element.text
        ]
        pallet_item_quantities = []
        for detail in inf_nfe.iter():
            if local_name(detail.tag) != "det":
                continue
            product_name = section_text(detail, "prod", "xProd")
            if not any(
                keyword in normalize_text(product_name)
                for keyword in self.pallet_keywords
            ):
                continue
            quantity = integer_quantity(section_text(detail, "prod", "qTrib"))
            if quantity is not None:
                pallet_item_quantities.append(quantity)
        pallet_quantity = (
            sum(pallet_item_quantities)
            if pallet_item_quantities
            else integer_quantity(section_text(root, "vol", "qVol"))
        )
        additional_info = " ".join(
            element.text.strip()
            for element in root.iter()
            if local_name(element.tag) in {"infCpl", "infAdFisco", "obsCont", "xTexto"}
            and element.text
        )
        searchable_text = all_xml_text(root)
        classification_text = normalize_text(" ".join([nature, *product_names, additional_info]))

        matched_keywords = [
            keyword for keyword in self.pallet_keywords if keyword in classification_text
        ]
        identified = bool(matched_keywords)
        reason = (
            "Palavra(s)-chave encontrada(s): " + ", ".join(matched_keywords)
            if identified
            else "Nenhuma palavra-chave de palete encontrada"
        )

        normalized_searchable_text = normalize_text(searchable_text)
        customer_order_match = re.search(
            r"PEDIDO DO CLIENTE\s*[:#=\-]?\s*(\d{4,20})"
            r"(?:\s+|[\-/,]\s*)(31M|31F|M*432)(?![A-Z0-9])",
            normalized_searchable_text,
        )
        transfer_order = bool(
            re.search(
                r"PEDIDO DO CLIENTE\s*[:#=\-]?\s*TRANSFERENCIA\b",
                normalized_searchable_text,
            )
        )
        shipment = (
            customer_order_match.group(1)
            if customer_order_match
            else "TRANSFERENCIA"
            if transfer_order
            else find_labeled_value(
                searchable_text,
                ("REMESSA", "ORDEM DE COLETA", "ORDEM COLETA", "NR REMESSA"),
                r"\d{4,20}",
            )
        )
        segment = find_labeled_value(
            searchable_text,
            ("SEGMENTO", "SEG"),
            r"31M|31F|M*432",
        )
        if not segment and customer_order_match:
            segment = customer_order_match.group(2)
        is_transfer_432_to_gma = (
            transfer_order
            and issuer_cnpj == FILIAL_432_CNPJ
            and recipient_cnpj == GMA_CNPJ
        )
        is_transfer_gma_to_432 = (
            transfer_order
            and issuer_cnpj == GMA_CNPJ
            and recipient_cnpj == FILIAL_432_CNPJ
        )
        is_special_branch_transfer = (
            is_transfer_432_to_gma or is_transfer_gma_to_432
        )
        if not segment and is_special_branch_transfer:
            segment = "PALETE"
        if not segment:
            segment_match = re.search(
                r"(?<![A-Z0-9])(31M|31F|M*432)(?![A-Z0-9])",
                normalized_searchable_text,
            )
            segment = segment_match.group(1) if segment_match else ""
        if re.fullmatch(r"M+432", segment):
            segment = "432"

        is_mdias = "M DIAS BRANCO" in normalize_text(recipient_name)
        is_own_carrier = "M DIAS BRANCO" in normalize_text(carrier_name)
        client = (
            "GMA"
            if is_transfer_432_to_gma
            else "432"
            if is_transfer_gma_to_432
            else f"M DIAS BRANCO - {recipient_city.upper()}"
            if is_mdias and recipient_city
            else f"M DIAS BRANCO - {recipient_uf}"
            if is_mdias and recipient_uf
            else "M DIAS BRANCO"
            if is_mdias
            else recipient_name
        )
        carrier = (
            "432"
            if is_transfer_432_to_gma
            else "GMA"
            if is_transfer_gma_to_432
            else "M DIAS BRANCO"
            if is_own_carrier
            else carrier_name
        )
        operation = "TRANSFERÊNCIA" if is_mdias else "VENDA"

        warnings = []
        if not identified:
            warnings.append("NF nao identificada automaticamente como NF de palete.")
        if not shipment:
            warnings.append("Numero da remessa nao encontrado.")
        if segment not in SEGMENTS:
            warnings.append("Segmento 31M, 31F, 432 ou PALETE nao encontrado.")
        if not recipient_uf:
            warnings.append("UF do destinatario nao encontrada.")
        if not access_key:
            warnings.append("Chave de acesso nao encontrada.")

        record = PalletRecord(
            nf_palete=nf_number,
            remessa=shipment,
            segmento=segment,
            transportadora=carrier,
            cliente=client,
            operacao=operation,
            uf_cliente=recipient_uf,
            quantidade_paletes=pallet_quantity,
            chave_acesso=access_key,
            emitente=issuer_name,
            data_emissao=issue_date[:10] if issue_date else "",
            identificada_palete=identified,
            motivo_identificacao=reason,
            arquivo_origem=filename,
            xml_original=xml_text,
        )
        return ParseResult(record=record, warnings=warnings)


class PalletDatabase:
    def __init__(self, path: str | Path = "controle_paletes.db"):
        self.path = str(path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS parametros (
                        segmento TEXT NOT NULL,
                        operacao TEXT NOT NULL,
                        quantidade_paletes INTEGER,
                        PRIMARY KEY (segmento, operacao)
                    );

                    CREATE TABLE IF NOT EXISTS registros (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nf_palete TEXT NOT NULL,
                        remessa TEXT,
                        segmento TEXT,
                        transportadora TEXT,
                        cliente TEXT,
                        operacao TEXT,
                        uf_cliente TEXT,
                        quantidade_paletes INTEGER,
                        chave_acesso TEXT NOT NULL UNIQUE,
                        emitente TEXT,
                        data_emissao TEXT,
                        identificada_palete INTEGER NOT NULL DEFAULT 0,
                        motivo_identificacao TEXT,
                        arquivo_origem TEXT,
                        xml_original TEXT,
                        criado_em TEXT NOT NULL,
                        atualizado_em TEXT NOT NULL
                    );
                    """
                )
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO parametros (segmento, operacao, quantidade_paletes)
                    VALUES (?, ?, NULL)
                    """,
                    [(segment, operation) for segment in SEGMENTS for operation in OPERATIONS],
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(registros)")
                }
                if "transportadora" not in columns:
                    connection.execute(
                        "ALTER TABLE registros ADD COLUMN transportadora TEXT"
                    )

    def get_expected_quantity(self, segment: str, operation: str) -> int | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT quantidade_paletes
                FROM parametros
                WHERE segmento = ? AND operacao = ?
                """,
                (segment, operation),
            ).fetchone()
        return row["quantidade_paletes"] if row else None

    def save(self, record: PalletRecord) -> None:
        if not record.chave_acesso:
            raise ValueError("A chave de acesso e obrigatoria para salvar o registro.")

        quantity = record.quantidade_paletes
        if quantity is None:
            quantity = self.get_expected_quantity(record.segmento, record.operacao)
        now = datetime.now().isoformat(timespec="seconds")
        values = asdict(record)
        values["quantidade_paletes"] = quantity
        values["identificada_palete"] = int(record.identificada_palete)
        values.update({"criado_em": now, "atualizado_em": now})

        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO registros (
                        nf_palete, remessa, segmento, transportadora, cliente,
                        operacao, uf_cliente,
                        quantidade_paletes, chave_acesso, emitente, data_emissao,
                        identificada_palete, motivo_identificacao, arquivo_origem,
                        xml_original, criado_em, atualizado_em
                    ) VALUES (
                        :nf_palete, :remessa, :segmento, :transportadora, :cliente,
                        :operacao, :uf_cliente,
                        :quantidade_paletes, :chave_acesso, :emitente, :data_emissao,
                        :identificada_palete, :motivo_identificacao, :arquivo_origem,
                        :xml_original, :criado_em, :atualizado_em
                    )
                    ON CONFLICT(chave_acesso) DO UPDATE SET
                        nf_palete = excluded.nf_palete,
                        remessa = excluded.remessa,
                        segmento = excluded.segmento,
                        transportadora = excluded.transportadora,
                        cliente = excluded.cliente,
                        operacao = excluded.operacao,
                        uf_cliente = excluded.uf_cliente,
                        quantidade_paletes = excluded.quantidade_paletes,
                        emitente = excluded.emitente,
                        data_emissao = excluded.data_emissao,
                        identificada_palete = excluded.identificada_palete,
                        motivo_identificacao = excluded.motivo_identificacao,
                        arquivo_origem = excluded.arquivo_origem,
                        xml_original = excluded.xml_original,
                        atualizado_em = excluded.atualizado_em
                    """,
                    values,
                )

    def list_records(self, search: str = "", operation: str = "", segment: str = "") -> pd.DataFrame:
        clauses = []
        params: list[str] = []
        if search:
            clauses.append(
                "(nf_palete LIKE ? OR remessa LIKE ? OR cliente LIKE ? OR chave_acesso LIKE ?)"
            )
            value = f"%{search}%"
            params.extend([value] * 4)
        if operation:
            clauses.append("operacao = ?")
            params.append(operation)
        if segment:
            clauses.append("segmento = ?")
            params.append(segment)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT
                substr(data_emissao, 9, 2) || '/' ||
                substr(data_emissao, 6, 2) || '/' ||
                substr(data_emissao, 1, 4) AS "Data",
                nf_palete AS "NF Palete",
                remessa AS "Remessa",
                segmento AS "Segmento",
                quantidade_paletes AS "Quantidade",
                transportadora AS "Transportadora",
                cliente AS "Cliente",
                CASE
                    WHEN operacao LIKE 'TRANSFER%' THEN 'Transferência'
                    WHEN operacao = 'VENDA' THEN 'Venda'
                    ELSE operacao
                END AS "Tipo Operação"
            FROM registros
            {where}
            ORDER BY criado_em DESC, id DESC
        """
        with closing(self.connect()) as connection:
            return pd.read_sql_query(query, connection, params=params)

    def list_parameters(self) -> pd.DataFrame:
        with closing(self.connect()) as connection:
            return pd.read_sql_query(
                """
                SELECT
                    segmento AS "Segmento",
                    operacao AS "Operacao",
                    quantidade_paletes AS "Quantidade Paletes"
                FROM parametros
                ORDER BY segmento, operacao
                """,
                connection,
            )

    def update_parameters(self, parameters: pd.DataFrame) -> None:
        with closing(self.connect()) as connection:
            with connection:
                for row in parameters.to_dict("records"):
                    quantity = row.get("Quantidade Paletes")
                    if pd.isna(quantity) or quantity == "":
                        quantity = None
                    else:
                        quantity = int(quantity)
                        if quantity < 0:
                            raise ValueError("A quantidade de paletes nao pode ser negativa.")

                    connection.execute(
                        """
                        UPDATE parametros
                        SET quantidade_paletes = ?
                        WHERE segmento = ? AND operacao = ?
                        """,
                        (quantity, row["Segmento"], row["Operacao"]),
                    )