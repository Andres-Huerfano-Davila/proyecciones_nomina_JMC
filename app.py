import io
import re
import unicodedata
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
APP_TITLE = "Modelo proyecciones nómina JMC V5"
DEFAULT_SMMLV = 1_750_905
DEFAULT_AUX_TRANSPORTE = 249_095

TIPO_CECO_BY_PREFIX_3 = {
    "101": "Tiendas",
    "102": "Logística",
    "103": "Admon",
}

TIPO_CECO_BY_ACCOUNT_PREFIX = {
    "60": "Tiendas",
    "62": "Logística",
    "63": "Admon",
}

# Conceptos base que se calculan desde MD / ingresos.
# Se pueden ampliar después, pero para esta fase dejamos nómina básica.
BASIC_SALARY_CONCEPTS = {
    "Y010",  # Sueldo Básico
    "Y011",  # Salario Part-time Días
    "Y020",  # Salario Integral
    "Y050",  # Apoyo de Sostenimiento
    "Y051",  # Apoyo Sostenimiento Pract
    "Y090",  # Salario Part-time Horas
}

AUX_TRANSPORTE_CONCEPT = "Y200"

AUX_ELIGIBLE_DESCRIPTIONS = {
    "sueldo basico",
    "salario parti-time dias",
    "salario part-time dias",
    "salario part time dias",
    "salario part-time horas",
    "salario part time horas",
    "apoyo sostenimiento pract",
}

# ============================================================
# UTILIDADES
# ============================================================
def strip_accents(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def norm_text(text) -> str:
    text = strip_accents(text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def norm_col(col) -> str:
    col = norm_text(col)
    col = col.replace(".", "").replace("/", " ").replace("-", " ")
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = re.sub(r"_+", "_", col).strip("_")
    return col


def find_col(df: pd.DataFrame, candidates: List[str], required: bool = False) -> Optional[str]:
    norm_map = {norm_col(c): c for c in df.columns}
    cand_norm = [norm_col(c) for c in candidates]
    for c in cand_norm:
        if c in norm_map:
            return norm_map[c]
    # Búsqueda por contiene
    for original in df.columns:
        n = norm_col(original)
        for c in cand_norm:
            if c and (c in n or n in c):
                return original
    if required:
        raise ValueError(f"No encontré ninguna columna para: {candidates}")
    return None


def to_number(x) -> float:
    if pd.isna(x):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return 0.0
    s = s.replace("$", "").replace("COP", "").replace(" ", "")
    # Formato colombiano: 1.750.905,00 o 1.750.905
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s and s.count(".") >= 1:
        parts = s.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def to_sap(x) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\D", "", s)
    return s


def to_concept(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip().upper()


def to_ceco(x) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\D", "", s)
    return s


def classify_ceco(ceco: str) -> str:
    ceco = to_ceco(ceco)
    return TIPO_CECO_BY_PREFIX_3.get(ceco[:3], "Sin clasificar")


def parse_date_value(x) -> Optional[pd.Timestamp]:
    if pd.isna(x) or x == "":
        return None
    try:
        ts = pd.to_datetime(x, errors="coerce", dayfirst=True)
        if pd.isna(ts):
            return None
        return pd.Timestamp(ts).normalize()
    except Exception:
        return None



def to_datetime_series(s: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(s, errors="coerce", dayfirst=True).dt.normalize()
    except Exception:
        return pd.to_datetime(pd.Series([pd.NaT] * len(s)), errors="coerce")


def is_9999_date(x) -> bool:
    ts = parse_date_value(x)
    return bool(ts is not None and ts.year >= 9999)


def inclusive_days(start: pd.Timestamp, end: pd.Timestamp) -> int:
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start:
        return 0
    return int((end - start).days) + 1


def days360_us(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Aproximación DAYS360 US. El archivo actual usa DAYS360(fecha_ini, fecha_fin + 1)."""
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start:
        return 0
    d1 = min(start.day, 30)
    d2 = end.day
    if d1 == 30 and d2 == 31:
        d2 = 30
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)


def working_days_mon_fri(start: pd.Timestamp, end: pd.Timestamp) -> int:
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start:
        return 0
    total = inclusive_days(start, end)
    weeks, rem = divmod(total, 7)
    wd = weeks * 5
    start_wd = start.weekday()
    for i in range(rem):
        if (start_wd + i) % 7 < 5:
            wd += 1
    return int(wd)


def count_weekend_days(start: pd.Timestamp, end: pd.Timestamp) -> int:
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start:
        return 0
    total = inclusive_days(start, end)
    weeks, rem = divmod(total, 7)
    we = weeks * 2
    start_wd = start.weekday()
    for i in range(rem):
        if (start_wd + i) % 7 >= 5:
            we += 1
    return int(we)


def calculate_paid_days(area_nomina: str, fecha_inicio: Optional[pd.Timestamp], fecha_retiro: Optional[pd.Timestamp],
                        periodo_ini: pd.Timestamp, periodo_fin: pd.Timestamp, dias_aus: float) -> Tuple[float, str]:
    area = norm_text(area_nomina)
    start = max(fecha_inicio or periodo_ini, periodo_ini)
    end = periodo_fin
    if fecha_retiro is not None and fecha_retiro.year < 9999:
        end = min(fecha_retiro, periodo_fin)

    if end < start:
        return 0.0, "Sin días en periodo"

    if "parcial" in area and "hora" in area:
        base_days = working_days_mon_fri(start, end)
        metodo = "Part time hora: días hábiles lunes-viernes"
    elif "parcial" in area and "dia" in area:
        base_days = count_weekend_days(start, end)
        metodo = "Part time día: sábados y domingos estimados"
    elif "365" in area:
        base_days = inclusive_days(start, end)
        metodo = "ZL / 365: días calendario"
    else:
        # ADMINISTRATIVOS / ZM: equivalente a DAYS360(fecha_ini, fecha_fin + 1)
        base_days = days360_us(start, end + pd.Timedelta(days=1))
        metodo = "ZM / 360: DAYS360"

    paid = max(float(base_days) - float(dias_aus or 0), 0.0)
    return paid, metodo


def safe_sheet_names(uploaded_file) -> List[str]:
    try:
        xls = pd.ExcelFile(uploaded_file)
        return xls.sheet_names
    except Exception:
        return []


def read_excel_safely(uploaded_file, preferred_sheet: Optional[str] = None, header: int = 0, dtype=str) -> pd.DataFrame:
    sheets = safe_sheet_names(uploaded_file)
    sheet = preferred_sheet if preferred_sheet in sheets else (sheets[0] if sheets else 0)
    uploaded_file.seek(0)
    return pd.read_excel(uploaded_file, sheet_name=sheet, header=header, dtype=dtype)


def detect_header_row(uploaded_file, sheet_name: Optional[str], required_terms: List[str], max_scan_rows: int = 15) -> int:
    uploaded_file.seek(0)
    raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=None, nrows=max_scan_rows, dtype=str)
    terms = [norm_text(t) for t in required_terms]
    best_row = 0
    best_score = -1
    for idx, row in raw.iterrows():
        joined = " | ".join(norm_text(v) for v in row.tolist() if pd.notna(v))
        score = sum(1 for t in terms if t in joined)
        if score > best_score:
            best_score = score
            best_row = idx
    return int(best_row)

# ============================================================
# LECTORES DE ARCHIVOS
# ============================================================
def build_dkon_matrix(dkon_file) -> pd.DataFrame:
    dkon_file.seek(0)
    df = pd.read_excel(dkon_file, sheet_name="Sheet1", dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    col_concepto = find_col(df, ["CC-nómina", "CC nomina", "CC-nomina"], required=True)
    col_txt = find_col(df, ["Txt.CC-nóm.", "Txt CC nom", "Texto CC nomina"])
    col_cta = find_col(df, ["Cta.mayor", "Cta mayor", "Cuenta mayor"], required=True)
    col_texto_cta = find_col(df, ["Texto breve", "Texto cuenta"])
    col_grupo = find_col(df, ["CUENTA", "Grupo", "Grupo de cuentas"])
    col_desc = find_col(df, ["Descripcion ", "Descripción", "Descripcion"])

    out = df.copy()
    out["Concepto"] = out[col_concepto].map(to_concept)
    out["Cuenta_DKON"] = out[col_cta].map(to_ceco)
    out = out[out["Concepto"].str.startswith("Y", na=False)].copy()
    out = out[out["Cuenta_DKON"].str[:2].isin(["60", "62", "63"])].copy()
    out["Tipo_CECO"] = out["Cuenta_DKON"].str[:2].map(TIPO_CECO_BY_ACCOUNT_PREFIX)
    out["Texto_Concepto_DKON"] = out[col_txt].fillna("") if col_txt else ""
    out["Texto_Cuenta"] = out[col_texto_cta].fillna("") if col_texto_cta else ""
    out["Grupo_DKON"] = out[col_grupo].fillna("") if col_grupo else ""
    out["Descripcion_DKON"] = out[col_desc].fillna("") if col_desc else ""

    cols = ["Concepto", "Texto_Concepto_DKON", "Tipo_CECO", "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON"]
    out = out[cols].drop_duplicates()

    # Si hay duplicados exactos por Concepto+Tipo_CECO, dejamos una sola combinación preferentemente con texto completo.
    out = out.sort_values(["Concepto", "Tipo_CECO", "Cuenta_DKON"])
    out = out.drop_duplicates(subset=["Concepto", "Tipo_CECO"], keep="first").reset_index(drop=True)
    return out


def read_md_dimension(md_file) -> pd.DataFrame:
    md_file.seek(0)
    df = pd.read_excel(md_file, sheet_name="Consolidado__Base", dtype=str)
    col_sap = find_col(df, ["Nº pers.", "N° pers.", "N pers", "SAP"], required=True)
    col_nombre = find_col(df, ["Número de personal", "Nombre", "Empleado"], required=True)
    col_area = find_col(df, ["Área de nómina", "Area de nomina"], required=True)
    col_ceco = find_col(df, ["Ce.coste", "Ce coste", "CECO"], required=True)
    col_centro = find_col(df, ["Centro de coste", "Centro de costo"])
    col_cargo = find_col(df, ["Función_2", "Funcion_2", "Función", "Funcion", "Cargo"])
    col_nivel = find_col(df, ["Gr.prof.", "Gr prof", "Nivel"])
    col_salario_total = find_col(df, ["Salario Total", "Importe"])
    col_fecha = find_col(df, ["Fecha", "Fecha alta", "Fecha de alta"])
    col_baja = find_col(df, ["Baja", "Fecha de baja"])
    col_tipo_sal = find_col(df, ["CC-nómina_2", "CC nomina_2", "Tipo Salario", "Tipo Sal"])
    col_concepto_sal = find_col(df, ["CC-nómina", "CC nomina"])

    out = pd.DataFrame()
    out["SAP"] = df[col_sap].map(to_sap)
    out["Nombre"] = df[col_nombre].fillna("").astype(str).str.strip()
    out["Area_Nomina"] = df[col_area].fillna("").astype(str).str.strip()
    out["CECO"] = df[col_ceco].map(to_ceco)
    out["Tipo_CECO"] = out["CECO"].map(classify_ceco)
    out["Centro_Coste"] = df[col_centro].fillna("").astype(str).str.strip() if col_centro else ""
    out["Cargo"] = df[col_cargo].fillna("").astype(str).str.strip() if col_cargo else ""
    out["Nivel"] = df[col_nivel].fillna("").astype(str).str.strip() if col_nivel else ""
    out["Salario_Total_MD"] = df[col_salario_total].map(to_number) if col_salario_total else 0.0
    out["Fecha_Ingreso"] = to_datetime_series(df[col_fecha]) if col_fecha else pd.NaT
    out["Fecha_Retiro"] = to_datetime_series(df[col_baja]) if col_baja else pd.NaT
    out["Tipo_Salario"] = df[col_tipo_sal].fillna("").astype(str).str.strip() if col_tipo_sal else ""
    out["Concepto_Salario_MD"] = df[col_concepto_sal].map(to_concept) if col_concepto_sal else ""
    out = out[out["SAP"] != ""].drop_duplicates(subset=["SAP"], keep="first").reset_index(drop=True)
    return out


def read_md_active_concepts(md_file) -> pd.DataFrame:
    md_file.seek(0)
    sheets = safe_sheet_names(md_file)
    sheet = "Salario_Bono_Vigente" if "Salario_Bono_Vigente" in sheets else "Consolidado__Base"
    md_file.seek(0)
    df = pd.read_excel(md_file, sheet_name=sheet, dtype=str)

    col_sap = find_col(df, ["Nº pers.", "N° pers.", "N pers", "SAP"], required=True)
    col_concepto = find_col(df, ["CC-nómina", "CC nomina", "CC-nomina"], required=True)
    col_txt = find_col(df, ["CC-nómina_2", "CC nomina_2", "Texto concepto", "Txt.CC-nóm."])
    col_importe = find_col(df, ["Importe", "Salario Total", "Valor"], required=True)
    col_hasta = find_col(df, ["Hasta", "Fecha hasta"])
    col_desde = find_col(df, ["Desde", "Fecha desde"])

    out = pd.DataFrame()
    out["SAP"] = df[col_sap].map(to_sap)
    out["Concepto"] = df[col_concepto].map(to_concept)
    out["Texto_Concepto"] = df[col_txt].fillna("").astype(str).str.strip() if col_txt else ""
    out["Importe_Mensual"] = df[col_importe].map(to_number)
    out["Desde"] = to_datetime_series(df[col_desde]) if col_desde else pd.NaT
    out["Hasta"] = to_datetime_series(df[col_hasta]) if col_hasta else pd.NaT

    out = out[(out["SAP"] != "") & (out["Concepto"].isin(BASIC_SALARY_CONCEPTS))].copy()
    if col_hasta:
        out = out[out["Hasta"].isna() | (out["Hasta"].dt.year >= 9999)].copy()
    out = out[out["Importe_Mensual"] != 0].copy()
    return out.reset_index(drop=True)


def read_absences(abs_file) -> pd.DataFrame:
    if abs_file is None:
        return pd.DataFrame(columns=["SAP", "Dias_Ausentismo"])
    sheets = safe_sheet_names(abs_file)
    sheet = "ausentismos" if "ausentismos" in sheets else sheets[0]
    header_row = detect_header_row(abs_file, sheet, ["Número de personal", "Dias", "Ausentismos"], max_scan_rows=10)
    abs_file.seek(0)
    df = pd.read_excel(abs_file, sheet_name=sheet, header=header_row, dtype=str)

    col_sap = find_col(df, ["Número de personal", "Nº pers.", "SAP"], required=True)
    col_dias = find_col(df, ["Dìas Ausentismos Real", "Días Ausentismos Real", "Dias Ausentismos Real", "Días presenc./abs.", "Dias presenc abs"], required=True)
    col_ok = find_col(df, ["correcto?", "correcto"])

    out = pd.DataFrame()
    out["SAP"] = df[col_sap].map(to_sap)
    out["Dias_Ausentismo"] = df[col_dias].map(to_number)
    if col_ok:
        mask_ok = df[col_ok].astype(str).str.lower().str.strip().isin(["true", "verdadero", "si", "sí", "1", "x"])
        # Si la columna está casi vacía no filtramos; si tiene valores válidos, sí.
        if mask_ok.sum() > 0:
            out = out[mask_ok].copy()
    out = out[out["SAP"] != ""]
    out = out.groupby("SAP", as_index=False)["Dias_Ausentismo"].sum()
    return out


def read_recruitment(recl_file) -> pd.DataFrame:
    if recl_file is None:
        return pd.DataFrame()
    sheets = safe_sheet_names(recl_file)
    sheet = "Proyección de Ingresos" if "Proyección de Ingresos" in sheets else sheets[0]
    recl_file.seek(0)
    df = pd.read_excel(recl_file, sheet_name=sheet, dtype=str)

    col_qty = find_col(df, ["# Posiciones", "Posiciones", "Cantidad", "Nombre Colaborador"], required=False)
    col_fecha = find_col(df, ["Fecha de ingreso", "Fecha ingreso"], required=True)
    col_cargo = find_col(df, ["Cargo", "Función", "Funcion"], required=False)
    col_ceco = find_col(df, ["Cecos", "Ce.coste", "CECO", "Centro de coste"], required=False)
    col_area = find_col(df, ["Área de nómina", "Area de nomina"], required=False)
    col_salario = find_col(df, ["Salario", "Importe"], required=False)
    col_region = find_col(df, ["Region", "Región"], required=False)
    col_tienda = find_col(df, ["Tienda", "Centro de coste"], required=False)
    col_nivel = find_col(df, ["Nivel", "Gr.prof.", "Gr prof"], required=False)

    df = df.copy()
    df["_fecha"] = to_datetime_series(df[col_fecha])
    df["_qty"] = df[col_qty].map(to_number).fillna(1).astype(float) if col_qty else 1
    if col_salario:
        df["_salario"] = df[col_salario].map(to_number)
    else:
        df["_salario"] = 0

    rows = []
    valid = df[df["_fecha"].notna()].copy()
    for idx, r in valid.iterrows():
        qty = int(max(r.get("_qty", 1), 0))
        if qty == 0:
            continue
        # Tope defensivo para evitar que una columna incorrecta genere miles de pseudoempleados por error.
        qty = min(qty, 200)
        fecha = r.get("_fecha")
        cargo = str(r.get(col_cargo, "") or "").strip() if col_cargo else ""
        ceco = to_ceco(r.get(col_ceco, "")) if col_ceco else ""
        if not ceco:
            # Si no viene CECO, estimamos por cargo/tienda.
            text = norm_text(f"{cargo} {r.get(col_tienda, '') if col_tienda else ''}")
            if "distrib" in text or "cedi" in text or "cd " in text:
                ceco = "1029999999"
            elif "admin" in text or "oficina" in text:
                ceco = "1039999999"
            else:
                ceco = "1019999999"
        area = str(r.get(col_area, "MENSUAL ADMON 365") or "MENSUAL ADMON 365").strip() if col_area else "MENSUAL ADMON 365"
        salario = float(r.get("_salario", 0) or 0)
        for n in range(qty):
            rows.append({
                "SAP": f"ING-{idx+1:04d}-{n+1}",
                "Nombre": f"Ingreso proyectado - {cargo}" if cargo else "Ingreso proyectado",
                "Area_Nomina": area,
                "CECO": ceco,
                "Tipo_CECO": classify_ceco(ceco),
                "Centro_Coste": str(r.get(col_tienda, "") or "").strip() if col_tienda else "",
                "Cargo": cargo,
                "Nivel": str(r.get(col_nivel, "") or "").strip() if col_nivel else "",
                "Salario_Total_MD": salario,
                "Fecha_Ingreso": fecha,
                "Fecha_Retiro": pd.NaT,
                "Tipo_Salario": "Sueldo Básico",
                "Concepto_Salario_MD": "Y010",
                "Fuente_Empleado": "Ingreso proyectado",
            })
    return pd.DataFrame(rows)

# ============================================================
# MOTOR DE CÁLCULO
# ============================================================
def calc_base_concepts(md_dim: pd.DataFrame, md_concepts: pd.DataFrame, abs_df: pd.DataFrame,
                       periodo_ini: pd.Timestamp, periodo_fin: pd.Timestamp,
                       smmlv: float, aux_transporte: float) -> pd.DataFrame:
    """Calcula nómina básica de forma vectorizada:
    - Conceptos salario desde MD vigente: Y010, Y011, Y020, Y050, Y051, Y090.
    - Auxilio transporte Y200 por empleado si aplica.
    """
    if md_dim.empty:
        return pd.DataFrame()

    aus_map = dict(zip(abs_df.get("SAP", []), abs_df.get("Dias_Ausentismo", [])))
    emp = md_dim.copy()
    emp["Dias_Ausentismo"] = emp["SAP"].map(aus_map).fillna(0).astype(float)

    # Días pagados se calculan una vez por empleado, no una vez por concepto.
    dias_records = []
    for _, r in emp.iterrows():
        dias, metodo = calculate_paid_days(
            r.get("Area_Nomina", ""),
            r.get("Fecha_Ingreso"),
            r.get("Fecha_Retiro"),
            periodo_ini,
            periodo_fin,
            r.get("Dias_Ausentismo", 0),
        )
        dias_records.append((r["SAP"], dias, metodo))
    dias_df = pd.DataFrame(dias_records, columns=["SAP", "Dias_Pagados", "Metodo_Dias"])
    emp = emp.merge(dias_df, on="SAP", how="left")

    detalle_parts = []

    # Conceptos base desde MD vigente.
    if not md_concepts.empty:
        base = md_concepts.merge(
            emp[["SAP", "Nombre", "Area_Nomina", "CECO", "Tipo_CECO", "Centro_Coste", "Cargo", "Nivel", "Dias_Ausentismo", "Dias_Pagados", "Metodo_Dias"]],
            on="SAP",
            how="left",
        )
        base["Periodo"] = periodo_ini.strftime("%Y-%m")
        area_norm = base["Area_Nomina"].fillna("").map(norm_text)
        is_part_hour = area_norm.str.contains("parcial") & area_norm.str.contains("hora")
        base["Valor"] = (base["Importe_Mensual"].astype(float) / 30 * base["Dias_Pagados"].astype(float))
        base.loc[is_part_hour, "Valor"] = base.loc[is_part_hour, "Importe_Mensual"].astype(float) / 220 * (base.loc[is_part_hour, "Dias_Pagados"].astype(float) * 4)
        base = base[base["Valor"] > 0].copy()
        base["Fuente"] = "MD actual - básico"
        base["Valor"] = base["Valor"].round(0)
        base["Dias_Pagados"] = base["Dias_Pagados"].round(4)
        cols = ["Periodo", "SAP", "Nombre", "Area_Nomina", "CECO", "Tipo_CECO", "Centro_Coste", "Cargo", "Nivel",
                "Concepto", "Texto_Concepto", "Fuente", "Importe_Mensual", "Dias_Ausentismo", "Dias_Pagados", "Metodo_Dias", "Valor"]
        detalle_parts.append(base[cols])

    # Auxilio de transporte por empleado.
    tipo_sal_norm = emp["Tipo_Salario"].fillna("").map(norm_text)
    eligible = tipo_sal_norm.isin(AUX_ELIGIBLE_DESCRIPTIONS) & (emp["Salario_Total_MD"].fillna(0).astype(float) <= (2 * smmlv)) & (emp["Dias_Pagados"].fillna(0).astype(float) > 0)
    aux = emp[eligible].copy()
    if not aux.empty:
        aux["Periodo"] = periodo_ini.strftime("%Y-%m")
        aux["Concepto"] = AUX_TRANSPORTE_CONCEPT
        aux["Texto_Concepto"] = "Auxilio de Transporte Legal"
        aux["Fuente"] = "MD actual - aux transporte"
        aux["Importe_Mensual"] = aux_transporte
        aux["Valor"] = (aux_transporte / 30 * aux["Dias_Pagados"].astype(float)).round(0)
        aux = aux[aux["Valor"] > 0].copy()
        cols = ["Periodo", "SAP", "Nombre", "Area_Nomina", "CECO", "Tipo_CECO", "Centro_Coste", "Cargo", "Nivel",
                "Concepto", "Texto_Concepto", "Fuente", "Importe_Mensual", "Dias_Ausentismo", "Dias_Pagados", "Metodo_Dias", "Valor"]
        detalle_parts.append(aux[cols])

    if detalle_parts:
        return pd.concat(detalle_parts, ignore_index=True)
    return pd.DataFrame()

def calc_recruitment_concepts(recl_df: pd.DataFrame, periodo_ini: pd.Timestamp, periodo_fin: pd.Timestamp,
                              smmlv: float, aux_transporte: float) -> pd.DataFrame:
    if recl_df.empty:
        return pd.DataFrame()
    records = []
    for _, r in recl_df.iterrows():
        dias, metodo = calculate_paid_days(r.get("Area_Nomina", ""), r.get("Fecha_Ingreso"), None, periodo_ini, periodo_fin, 0)
        salario = float(r.get("Salario_Total_MD", 0) or 0)
        valor = salario / 30 * dias
        if valor > 0:
            records.append({
                "Periodo": periodo_ini.strftime("%Y-%m"),
                "SAP": r["SAP"],
                "Nombre": r.get("Nombre", ""),
                "Area_Nomina": r.get("Area_Nomina", ""),
                "CECO": r.get("CECO", ""),
                "Tipo_CECO": r.get("Tipo_CECO", ""),
                "Centro_Coste": r.get("Centro_Coste", ""),
                "Cargo": r.get("Cargo", ""),
                "Nivel": r.get("Nivel", ""),
                "Concepto": "Y010",
                "Texto_Concepto": "Sueldo Básico - Ingreso proyectado",
                "Fuente": "Ingreso reclutamiento",
                "Importe_Mensual": salario,
                "Dias_Ausentismo": 0,
                "Dias_Pagados": round(dias, 4),
                "Metodo_Dias": metodo,
                "Valor": round(valor, 0),
            })
        if salario <= 2 * smmlv:
            aux = aux_transporte / 30 * dias
            if aux > 0:
                records.append({
                    "Periodo": periodo_ini.strftime("%Y-%m"),
                    "SAP": r["SAP"],
                    "Nombre": r.get("Nombre", ""),
                    "Area_Nomina": r.get("Area_Nomina", ""),
                    "CECO": r.get("CECO", ""),
                    "Tipo_CECO": r.get("Tipo_CECO", ""),
                    "Centro_Coste": r.get("Centro_Coste", ""),
                    "Cargo": r.get("Cargo", ""),
                    "Nivel": r.get("Nivel", ""),
                    "Concepto": AUX_TRANSPORTE_CONCEPT,
                    "Texto_Concepto": "Auxilio de Transporte Legal - Ingreso proyectado",
                    "Fuente": "Ingreso reclutamiento",
                    "Importe_Mensual": aux_transporte,
                    "Dias_Ausentismo": 0,
                    "Dias_Pagados": round(dias, 4),
                    "Metodo_Dias": metodo,
                    "Valor": round(aux, 0),
                })
    return pd.DataFrame(records)


def homologate_to_dkon(base_conceptos: pd.DataFrame, dkon_matrix: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if base_conceptos.empty:
        return pd.DataFrame(), pd.DataFrame()
    out = base_conceptos.merge(dkon_matrix, on=["Concepto", "Tipo_CECO"], how="left")
    missing = out[out["Cuenta_DKON"].isna() | (out["Cuenta_DKON"].astype(str).str.strip() == "")].copy()
    group_cols = [
        "Periodo", "SAP", "Nombre", "Area_Nomina", "CECO", "Tipo_CECO", "Centro_Coste", "Cargo", "Nivel",
        "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON", "Fuente",
    ]
    ok = out[~out.index.isin(missing.index)].copy()
    if ok.empty:
        return ok, missing
    agg = ok.groupby(group_cols, dropna=False).agg(
        Valor=("Valor", "sum"),
        Conceptos_Agrupados=("Concepto", lambda s: ", ".join(sorted(set(str(x) for x in s if str(x) != "nan")))),
        Dias_Pagados_Prom=("Dias_Pagados", "mean"),
    ).reset_index()
    agg["Valor"] = agg["Valor"].round(0)
    return agg, missing


def build_alerts(md_dim: pd.DataFrame, base: pd.DataFrame, missing: pd.DataFrame) -> pd.DataFrame:
    alerts = []
    for _, r in md_dim[md_dim["Tipo_CECO"] == "Sin clasificar"].iterrows():
        alerts.append({"Tipo": "CECO sin clasificar", "SAP": r.get("SAP"), "Detalle": r.get("CECO"), "Valor": None})
    for _, r in base[base["Valor"].isna() | (base["Valor"] == 0)].iterrows():
        alerts.append({"Tipo": "Valor cero o vacío", "SAP": r.get("SAP"), "Detalle": r.get("Concepto"), "Valor": r.get("Valor")})
    for _, r in missing.iterrows():
        alerts.append({"Tipo": "Concepto sin cuenta DKON", "SAP": r.get("SAP"), "Detalle": f"{r.get('Concepto')} / {r.get('Tipo_CECO')}", "Valor": r.get("Valor")})
    return pd.DataFrame(alerts)


def build_excel_output(dfs: Dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for name, df in dfs.items():
            safe_name = name[:31]
            if df is None or df.empty:
                pd.DataFrame({"Mensaje": ["Sin registros"]}).to_excel(writer, sheet_name=safe_name, index=False)
            else:
                export_df = df.copy()
                # Excel no soporta tz; convertimos timestamps a fecha simple.
                for c in export_df.columns:
                    if pd.api.types.is_datetime64_any_dtype(export_df[c]):
                        export_df[c] = export_df[c].dt.strftime("%d/%m/%Y")
                export_df.to_excel(writer, sheet_name=safe_name, index=False)
                ws = writer.sheets[safe_name]
                ws.freeze_panes(1, 0)
                for idx, col in enumerate(export_df.columns):
                    max_len = min(max([len(str(col))] + [len(str(v)) for v in export_df[col].head(200).fillna("").tolist()]) + 2, 42)
                    ws.set_column(idx, idx, max_len)
                # Formato básico
                workbook = writer.book
                header_fmt = workbook.add_format({"bold": True, "bg_color": "#F59E0B", "font_color": "#FFFFFF", "border": 1})
                money_fmt = workbook.add_format({"num_format": "#,##0"})
                for col_idx, col_name in enumerate(export_df.columns):
                    ws.write(0, col_idx, col_name, header_fmt)
                    if norm_col(col_name) in ["valor", "importe_mensual", "salario_total_md"] or "valor" in norm_col(col_name):
                        ws.set_column(col_idx, col_idx, 16, money_fmt)
    output.seek(0)
    return output.getvalue()

# ============================================================
# UI STREAMLIT
# ============================================================
st.set_page_config(page_title=APP_TITLE, page_icon="💼", layout="wide")

st.markdown(
    """
    <style>
    .main {background: linear-gradient(180deg, #fff7ed 0%, #ffffff 30%);} 
    .block-container {padding-top: 1.2rem;}
    .big-title {font-size: 2.1rem; font-weight: 800; color: #7c2d12; margin-bottom: .2rem;}
    .subtitle {font-size: 1rem; color: #57534e; margin-bottom: 1.3rem;}
    div[data-testid="stMetric"] {background:#fff7ed; border:1px solid #fed7aa; padding:12px; border-radius:14px;}
    .footer {font-size:.82rem; color:#78716c; margin-top:2rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="big-title">💼 Modelo proyecciones de nómina JMC</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">MVP 3 · Calcula conceptos básicos de nómina, ingresos proyectados, ausentismos y homologación DKON por CECO.</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Parámetros")
    periodo_ini = pd.Timestamp(st.date_input("Fecha inicio del periodo", value=date(2026, 5, 1)))
    periodo_fin = pd.Timestamp(st.date_input("Fecha fin del periodo", value=date(2026, 5, 31)))
    smmlv = st.number_input("SMMLV", min_value=0, value=DEFAULT_SMMLV, step=1000, format="%d")
    aux_transporte = st.number_input("Auxilio transporte legal", min_value=0, value=DEFAULT_AUX_TRANSPORTE, step=1000, format="%d")

st.subheader("1. Carga de archivos")
col1, col2, col3 = st.columns(3)
with col1:
    dkon_file = st.file_uploader("DKON", type=["xlsx", "xlsm", "xls"], key="dkon")
with col2:
    md_ant_file = st.file_uploader("MD mes anterior", type=["xlsx", "xlsm", "xls"], key="md_ant")
with col3:
    md_act_file = st.file_uploader("MD mes actual", type=["xlsx", "xlsm", "xls"], key="md_act")

col4, col5 = st.columns(2)
with col4:
    recl_file = st.file_uploader("Ingresos reclutamiento / proyección ingresos (opcional)", type=["xlsx", "xlsm", "xls"], key="recl")
with col5:
    abs_file = st.file_uploader("Proyección ausentismos (opcional)", type=["xlsx", "xlsm", "xls"], key="abs")

st.info("En esta fase el cálculo se concentra en conceptos básicos: Y010/Y011/Y020/Y050/Y051/Y090 y auxilio de transporte Y200. Después conectamos horas, bonos, retiros y provisiones.")

if st.button("🚀 Generar base MVP 3", type="primary", use_container_width=False):
    if not dkon_file or not md_act_file:
        st.error("Para generar la base necesitas cargar mínimo DKON y MD mes actual.")
        st.stop()
    try:
        with st.spinner("Leyendo DKON y construyendo matriz de cuentas..."):
            dkon_matrix = build_dkon_matrix(dkon_file)

        with st.spinner("Leyendo MD actual..."):
            md_dim = read_md_dimension(md_act_file)
            md_concepts = read_md_active_concepts(md_act_file)

        with st.spinner("Leyendo ausentismos..."):
            abs_df = read_absences(abs_file) if abs_file else pd.DataFrame(columns=["SAP", "Dias_Ausentismo"])

        with st.spinner("Calculando conceptos básicos desde MD..."):
            base_md = calc_base_concepts(md_dim, md_concepts, abs_df, periodo_ini, periodo_fin, smmlv, aux_transporte)

        with st.spinner("Procesando ingresos proyectados..."):
            recl_df = read_recruitment(recl_file) if recl_file else pd.DataFrame()
            base_ing = calc_recruitment_concepts(recl_df, periodo_ini, periodo_fin, smmlv, aux_transporte) if not recl_df.empty else pd.DataFrame()

        base_conceptos = pd.concat([df for df in [base_md, base_ing] if df is not None and not df.empty], ignore_index=True) if (not base_md.empty or not base_ing.empty) else pd.DataFrame()

        with st.spinner("Homologando a cuentas DKON..."):
            base_cuentas, sin_cuenta = homologate_to_dkon(base_conceptos, dkon_matrix)
            alertas = build_alerts(md_dim, base_conceptos, sin_cuenta)

        resumen_tipo = base_cuentas.groupby(["Tipo_CECO", "Grupo_DKON"], dropna=False)["Valor"].sum().reset_index() if not base_cuentas.empty else pd.DataFrame()
        resumen_cuenta = base_cuentas.groupby(["Tipo_CECO", "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON"], dropna=False)["Valor"].sum().reset_index() if not base_cuentas.empty else pd.DataFrame()
        resumen_ceco = base_cuentas.groupby(["Tipo_CECO", "CECO", "Centro_Coste", "Cuenta_DKON", "Texto_Cuenta"], dropna=False)["Valor"].sum().reset_index() if not base_cuentas.empty else pd.DataFrame()

        comparativo_md = pd.DataFrame()
        resumen_mov = pd.DataFrame()
        if md_ant_file:
            with st.spinner("Construyendo comparativo MD..."):
                md_ant_dim = read_md_dimension(md_ant_file)
                ant = md_ant_dim[["SAP", "Nombre", "CECO", "Tipo_CECO", "Salario_Total_MD"]].rename(columns={
                    "Nombre": "Nombre_Ant", "CECO": "CECO_Ant", "Tipo_CECO": "Tipo_CECO_Ant", "Salario_Total_MD": "Salario_Ant"
                })
                act = md_dim[["SAP", "Nombre", "CECO", "Tipo_CECO", "Salario_Total_MD"]].rename(columns={
                    "Nombre": "Nombre_Act", "CECO": "CECO_Act", "Tipo_CECO": "Tipo_CECO_Act", "Salario_Total_MD": "Salario_Act"
                })
                comparativo_md = ant.merge(act, on="SAP", how="outer")
                comparativo_md["Estado"] = comparativo_md.apply(
                    lambda r: "Nuevo" if pd.isna(r["CECO_Ant"]) else ("Salida" if pd.isna(r["CECO_Act"]) else "Continúa"), axis=1
                )
                comparativo_md["Cambio_CECO"] = (comparativo_md["CECO_Ant"].fillna("") != comparativo_md["CECO_Act"].fillna("")) & (comparativo_md["Estado"] == "Continúa")
                comparativo_md["Dif_Salario"] = comparativo_md["Salario_Act"].fillna(0) - comparativo_md["Salario_Ant"].fillna(0)
                resumen_mov = pd.concat([
                    comparativo_md.groupby("Tipo_CECO_Ant", dropna=False).agg(HC_Mes_Anterior=("SAP", "count")).rename_axis("Tipo_CECO").reset_index(),
                    comparativo_md.groupby("Tipo_CECO_Act", dropna=False).agg(HC_MD_Actual=("SAP", "count")).rename_axis("Tipo_CECO").reset_index(),
                ], ignore_index=False)

        st.success("Base generada correctamente.")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Conceptos Y DKON", f"{dkon_matrix['Concepto'].nunique():,}")
        m2.metric("HC MD actual", f"{md_dim['SAP'].nunique():,}")
        m3.metric("Registros concepto", f"{len(base_conceptos):,}")
        m4.metric("Ingresos proyectados", f"{len(recl_df):,}" if not recl_df.empty else "0")
        m5.metric("Alertas", f"{len(alertas):,}")

        st.subheader("Vista previa - Detalle por concepto")
        st.dataframe(base_conceptos.head(50), use_container_width=True)

        st.subheader("Vista previa - Agrupado por cuenta DKON")
        st.dataframe(base_cuentas.head(50), use_container_width=True)

        tabs = st.tabs(["Resumen cuenta", "Resumen CECO", "Resumen tipo", "Ausentismos", "Ingresos", "Alertas"])
        with tabs[0]:
            st.dataframe(resumen_cuenta, use_container_width=True)
        with tabs[1]:
            st.dataframe(resumen_ceco, use_container_width=True)
        with tabs[2]:
            st.dataframe(resumen_tipo, use_container_width=True)
        with tabs[3]:
            st.dataframe(abs_df, use_container_width=True)
        with tabs[4]:
            st.dataframe(recl_df, use_container_width=True)
        with tabs[5]:
            st.dataframe(alertas, use_container_width=True)

        dfs = {
            "MATRIZ_DKON_Y": dkon_matrix,
            "MD_NORMALIZADO": md_dim,
            "AUSENTISMOS_RESUMEN": abs_df,
            "INGRESOS_PROYECTADOS": recl_df,
            "BASE_DETALLE_CONCEPTO": base_conceptos,
            "BASE_CUENTAS_DKON": base_cuentas,
            "RESUMEN_CUENTA": resumen_cuenta,
            "RESUMEN_CECO": resumen_ceco,
            "RESUMEN_TIPO_CECO": resumen_tipo,
            "COMPARATIVO_MD": comparativo_md,
            "ALERTAS": alertas,
        }
        xlsx_bytes = build_excel_output(dfs)
        st.download_button(
            "📥 Descargar base Excel MVP 3",
            data=xlsx_bytes,
            file_name=f"base_proyeccion_costos_mvp3_{periodo_ini.strftime('%Y_%m')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    except Exception as e:
        st.exception(e)
        st.error("Se presentó un error. Revisa que los archivos tengan las hojas y columnas esperadas.")

st.markdown('<div class="footer">Creado por Andrés Huérfano Dávila – Nómina JMC</div>', unsafe_allow_html=True)
