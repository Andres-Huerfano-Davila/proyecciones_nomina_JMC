import io
import re
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

# =====================================================
# PROYECCIÓN COSTOS JMC - MVP 2
# Motor base: DKON + MD Mes Anterior + MD Actual
# Objetivo: construir base detalle por concepto Y, base por cuenta DKON
# y comparativo de planta entre MD anterior y MD actual.
# =====================================================

st.set_page_config(
    page_title="Proyección de Costos JMC",
    page_icon="🦜",
    layout="wide",
)

PRIMARY = "#F97316"
SOFT = "#FFF7ED"
DARK = "#7C2D12"

st.markdown(
    f"""
    <style>
    .main {{background-color: #FFFFFF;}}
    .block-container {{padding-top: 1.5rem; padding-bottom: 2rem;}}
    h1, h2, h3 {{color: {DARK};}}
    div[data-testid="stMetric"] {{background-color: {SOFT}; border: 1px solid #FED7AA; padding: 12px; border-radius: 14px;}}
    .stButton button {{background-color: {PRIMARY}; color: white; border-radius: 10px; border: none;}}
    .stDownloadButton button {{background-color: {PRIMARY}; color: white; border-radius: 10px; border: none;}}
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# Utilidades generales
# ----------------------------

def normalizar_texto(x):
    if pd.isna(x):
        return ""
    x = str(x).strip()
    x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", x)


def norm_col(c):
    c = normalizar_texto(c).lower()
    c = re.sub(r"[^a-z0-9]+", "_", c)
    return c.strip("_")


def clean_code(x):
    if pd.isna(x):
        return ""
    x = str(x).strip().upper()
    if re.fullmatch(r"\d+\.0", x):
        x = x[:-2]
    return x


def clean_ceco(x):
    if pd.isna(x):
        return ""
    x = str(x).strip()
    x = re.sub(r"\.0$", "", x)
    x = re.sub(r"\D", "", x)
    return x


def to_number(value):
    """Convierte '1.750.905', '1,750,905', '$ 1.750.905' a número."""
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace("$", "").replace("COP", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s and "," not in s:
        parts = s.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")
    elif "," in s and "." not in s:
        parts = s.split(",")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    s = re.sub(r"[^0-9\.-]", "", s)
    try:
        return float(s)
    except Exception:
        return 0.0


def clasificar_tipo_ceco(ceco):
    ceco = clean_ceco(ceco)
    if ceco.startswith("101"):
        return "Tiendas"
    if ceco.startswith("102"):
        return "Logística"
    if ceco.startswith("103"):
        return "Admon"
    return "Sin clasificar"


def clasificar_tipo_cuenta(cuenta):
    cuenta = clean_ceco(cuenta)
    if cuenta.startswith("60"):
        return "Tiendas"
    if cuenta.startswith("62"):
        return "Logística"
    if cuenta.startswith("63"):
        return "Admon"
    return "Sin clasificar"


def find_sheet_name(uploaded_file, preferred_names):
    uploaded_file.seek(0)
    xls = pd.ExcelFile(uploaded_file)
    norm_map = {norm_col(s): s for s in xls.sheet_names}
    for name in preferred_names:
        n = norm_col(name)
        if n in norm_map:
            return norm_map[n]
    return xls.sheet_names[0]


def pick_col(df, candidates, required=True):
    col_map = {norm_col(c): c for c in df.columns}
    for cand in candidates:
        n = norm_col(cand)
        if n in col_map:
            return col_map[n]
    for cand in candidates:
        n = norm_col(cand)
        for k, v in col_map.items():
            if n and n in k:
                return v
    if required:
        raise ValueError(f"No encontré columna requerida. Candidatas: {candidates}")
    return None


def safe_series(df, col, default=""):
    if col and col in df.columns:
        return df[col].fillna("").astype(str).str.strip()
    return pd.Series([default] * len(df), index=df.index)

# ----------------------------
# DKON
# ----------------------------

def construir_matriz_dkon(dkon_file):
    sh = find_sheet_name(dkon_file, ["Sheet1"])
    dkon_file.seek(0)
    df = pd.read_excel(dkon_file, sheet_name=sh, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    col_concepto = pick_col(df, ["CC-nómina", "CC nomina", "Concepto"])
    col_texto_concepto = pick_col(df, ["Txt.CC-nóm.", "Txt CC nom", "Texto concepto"], required=False)
    col_cuenta = pick_col(df, ["Cta.mayor", "Cuenta mayor", "Cta mayor"])
    col_texto_cuenta = pick_col(df, ["Texto breve", "Texto cuenta"], required=False)
    col_grupo = pick_col(df, ["CUENTA", "Grupo de cuentas", "Grupo"], required=False)
    col_descripcion = pick_col(df, ["Descripcion", "Descripción", "Descripcion "], required=False)

    matriz = df.copy()
    matriz["Concepto"] = matriz[col_concepto].map(clean_code)
    matriz = matriz[matriz["Concepto"].str.startswith("Y", na=False)].copy()

    matriz["Cuenta_DKON"] = matriz[col_cuenta].map(clean_ceco)
    matriz = matriz[matriz["Cuenta_DKON"].str.match(r"^(60|62|63)\d+", na=False)].copy()
    matriz["Tipo_CECO"] = matriz["Cuenta_DKON"].map(clasificar_tipo_cuenta)

    matriz["Descripcion_Concepto"] = safe_series(matriz, col_texto_concepto)
    matriz["Texto_Cuenta"] = safe_series(matriz, col_texto_cuenta)
    matriz["Grupo_DKON"] = safe_series(matriz, col_grupo)
    matriz["Descripcion_DKON"] = safe_series(matriz, col_descripcion)

    matriz = matriz[[
        "Concepto",
        "Descripcion_Concepto",
        "Tipo_CECO",
        "Cuenta_DKON",
        "Texto_Cuenta",
        "Grupo_DKON",
        "Descripcion_DKON",
    ]].copy()

    for c in matriz.columns:
        matriz[c] = matriz[c].fillna("").astype(str).str.strip()

    matriz = matriz.drop_duplicates(subset=["Concepto", "Tipo_CECO"], keep="first")
    matriz["Llave_DKON"] = matriz["Tipo_CECO"] + "|" + matriz["Concepto"]

    return matriz.sort_values(["Concepto", "Tipo_CECO"]).reset_index(drop=True)

# ----------------------------
# MD
# ----------------------------

def leer_md_conceptos(md_file, fuente="MD Actual"):
    """Lee Salario_Bono_Vigente para obtener detalle por concepto Y."""
    sh = find_sheet_name(md_file, ["Salario_Bono_Vigente", "Consolidado__Base"])
    md_file.seek(0)
    df = pd.read_excel(md_file, sheet_name=sh, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    col_sap = pick_col(df, ["Nº pers.", "N° pers.", "No pers", "SAP", "Número de personal"])
    col_nombre = pick_col(df, ["Número de personal", "Nombre"], required=False)
    col_status = pick_col(df, ["Status ocupación", "Status ocupacion"], required=False)
    col_area_nomina = pick_col(df, ["Área de nómina", "Area de nomina"], required=False)
    col_ceco = pick_col(df, ["Ce.coste", "Ce coste", "Centro costo", "Centro de costo"])
    col_centro = pick_col(df, ["Centro de coste", "Centro de costo"], required=False)
    col_funcion = pick_col(df, ["Función_2", "Funcion_2", "Función", "Funcion", "Cargo", "Posición_2"], required=False)
    col_concepto = pick_col(df, ["CC-nómina", "CC nomina", "Concepto"])
    col_desc_concepto = pick_col(df, ["CC-nómina_2", "CC nomina_2", "Texto concepto"], required=False)
    col_importe = pick_col(df, ["Importe", "Salario Total", "Valor"], required=False)
    col_nivel = pick_col(df, ["Gr.prof.", "Gr prof", "Nivel"], required=False)
    col_division = pick_col(df, ["División de personal", "Division de personal"], required=False)
    col_regional = pick_col(df, ["Encargado para registro de tie", "Regional"], required=False)
    col_id = pick_col(df, ["Número ID", "Numero ID", "Cedula", "Cédula"], required=False)

    out = pd.DataFrame()
    out["SAP"] = df[col_sap].map(clean_code)
    out["Nombre"] = safe_series(df, col_nombre)
    out["Status"] = safe_series(df, col_status)
    out["Area_Nomina"] = safe_series(df, col_area_nomina)
    out["CECO"] = df[col_ceco].map(clean_ceco)
    out["Centro_Coste"] = safe_series(df, col_centro)
    out["Tipo_CECO"] = out["CECO"].map(clasificar_tipo_ceco)
    out["Cargo"] = safe_series(df, col_funcion)
    out["Nivel"] = safe_series(df, col_nivel)
    out["Division_Personal"] = safe_series(df, col_division)
    out["Regional"] = safe_series(df, col_regional)
    out["Numero_ID"] = safe_series(df, col_id)
    out["Concepto"] = df[col_concepto].map(clean_code)
    out["Descripcion_Concepto_MD"] = safe_series(df, col_desc_concepto)
    out["Valor"] = df[col_importe].map(to_number) if col_importe else 0.0
    out["Fuente"] = fuente

    out = out[out["Concepto"].str.startswith("Y", na=False)].copy()
    out = out[out["SAP"].ne("")].copy()
    return out.reset_index(drop=True)


def leer_md_dimension(md_file, etiqueta="Actual"):
    """Lee Consolidado__Base para obtener una fila por SAP para comparativo de planta."""
    sh = find_sheet_name(md_file, ["Consolidado__Base", "Salario_Bono_Vigente"])
    md_file.seek(0)
    df = pd.read_excel(md_file, sheet_name=sh, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    col_sap = pick_col(df, ["Nº pers.", "N° pers.", "No pers", "SAP", "Número de personal"])
    col_nombre = pick_col(df, ["Número de personal", "Nombre"], required=False)
    col_status = pick_col(df, ["Status ocupación", "Status ocupacion"], required=False)
    col_area_nomina = pick_col(df, ["Área de nómina", "Area de nomina"], required=False)
    col_ceco = pick_col(df, ["Ce.coste", "Ce coste", "Centro costo", "Centro de costo"])
    col_centro = pick_col(df, ["Centro de coste", "Centro de costo"], required=False)
    col_funcion = pick_col(df, ["Función_2", "Funcion_2", "Función", "Funcion", "Cargo", "Posición_2"], required=False)
    col_salario = pick_col(df, ["Salario Total", "salario_total", "Importe", "Valor"], required=False)
    col_nivel = pick_col(df, ["Gr.prof.", "Gr prof", "Nivel"], required=False)
    col_division = pick_col(df, ["División de personal", "Division de personal"], required=False)
    col_regional = pick_col(df, ["Encargado para registro de tie", "Regional"], required=False)
    col_id = pick_col(df, ["Número ID", "Numero ID", "Cedula", "Cédula"], required=False)

    out = pd.DataFrame()
    out["SAP"] = df[col_sap].map(clean_code)
    out["Nombre"] = safe_series(df, col_nombre)
    out["Status"] = safe_series(df, col_status)
    out["Area_Nomina"] = safe_series(df, col_area_nomina)
    out["CECO"] = df[col_ceco].map(clean_ceco)
    out["Centro_Coste"] = safe_series(df, col_centro)
    out["Tipo_CECO"] = out["CECO"].map(clasificar_tipo_ceco)
    out["Cargo"] = safe_series(df, col_funcion)
    out["Nivel"] = safe_series(df, col_nivel)
    out["Division_Personal"] = safe_series(df, col_division)
    out["Regional"] = safe_series(df, col_regional)
    out["Numero_ID"] = safe_series(df, col_id)
    out["Salario_Total"] = df[col_salario].map(to_number) if col_salario else 0.0
    out = out[out["SAP"].ne("")].copy()

    # Si por alguna razón hay más de una fila por SAP, se conserva la primera fila no vacía.
    out = out.sort_values(["SAP"]).drop_duplicates(subset=["SAP"], keep="first").reset_index(drop=True)
    out["Etiqueta_MD"] = etiqueta
    return out


def crear_base_conceptos(md_conceptos, periodo):
    base = md_conceptos.copy()
    base.insert(0, "Periodo", periodo)
    base["Llave_DKON"] = base["Tipo_CECO"] + "|" + base["Concepto"]
    cols = [
        "Periodo", "SAP", "Nombre", "Status", "Area_Nomina", "CECO", "Centro_Coste", "Tipo_CECO",
        "Cargo", "Nivel", "Division_Personal", "Regional", "Numero_ID", "Concepto", "Descripcion_Concepto_MD",
        "Valor", "Fuente", "Llave_DKON"
    ]
    return base[cols].copy()

# ----------------------------
# Comparativo MD
# ----------------------------

def construir_comparativo_md(md_ant_dim, md_act_dim):
    ant = md_ant_dim.rename(columns={c: f"{c}_ANT" for c in md_ant_dim.columns if c not in ["SAP"]})
    act = md_act_dim.rename(columns={c: f"{c}_ACT" for c in md_act_dim.columns if c not in ["SAP"]})
    comp = ant.merge(act, on="SAP", how="outer", indicator=True)

    def estado(row):
        if row["_merge"] == "left_only":
            return "No está en MD actual"
        if row["_merge"] == "right_only":
            return "Nuevo en MD actual"
        return "Continúa"

    comp["Estado_Planta"] = comp.apply(estado, axis=1)

    def neq(a, b):
        a = "" if pd.isna(a) else str(a).strip()
        b = "" if pd.isna(b) else str(b).strip()
        return a != b

    comp["Cambio_CECO"] = comp.apply(lambda r: r["Estado_Planta"] == "Continúa" and neq(r.get("CECO_ANT"), r.get("CECO_ACT")), axis=1)
    comp["Cambio_Tipo_CECO"] = comp.apply(lambda r: r["Estado_Planta"] == "Continúa" and neq(r.get("Tipo_CECO_ANT"), r.get("Tipo_CECO_ACT")), axis=1)
    comp["Cambio_Cargo"] = comp.apply(lambda r: r["Estado_Planta"] == "Continúa" and neq(r.get("Cargo_ANT"), r.get("Cargo_ACT")), axis=1)
    comp["Cambio_Area_Nomina"] = comp.apply(lambda r: r["Estado_Planta"] == "Continúa" and neq(r.get("Area_Nomina_ANT"), r.get("Area_Nomina_ACT")), axis=1)
    comp["Diferencia_Salario"] = comp.get("Salario_Total_ACT", 0).fillna(0).astype(float) - comp.get("Salario_Total_ANT", 0).fillna(0).astype(float)
    comp["Cambio_Salario"] = comp["Estado_Planta"].eq("Continúa") & comp["Diferencia_Salario"].abs().gt(1)

    def movimiento(row):
        if row["Estado_Planta"] != "Continúa":
            return row["Estado_Planta"]
        cambios = []
        if row["Cambio_CECO"]:
            cambios.append("Cambio CECO")
        if row["Cambio_Tipo_CECO"]:
            cambios.append("Cambio tipo CECO")
        if row["Cambio_Salario"]:
            cambios.append("Cambio salario")
        if row["Cambio_Cargo"]:
            cambios.append("Cambio cargo")
        if row["Cambio_Area_Nomina"]:
            cambios.append("Cambio área nómina")
        return "; ".join(cambios) if cambios else "Sin cambio relevante"

    comp["Movimiento"] = comp.apply(movimiento, axis=1)

    columnas = [
        "SAP", "Estado_Planta", "Movimiento",
        "Nombre_ANT", "Nombre_ACT", "Numero_ID_ANT", "Numero_ID_ACT",
        "CECO_ANT", "CECO_ACT", "Tipo_CECO_ANT", "Tipo_CECO_ACT",
        "Centro_Coste_ANT", "Centro_Coste_ACT",
        "Area_Nomina_ANT", "Area_Nomina_ACT", "Cargo_ANT", "Cargo_ACT",
        "Nivel_ANT", "Nivel_ACT", "Regional_ANT", "Regional_ACT",
        "Salario_Total_ANT", "Salario_Total_ACT", "Diferencia_Salario",
        "Cambio_CECO", "Cambio_Tipo_CECO", "Cambio_Salario", "Cambio_Cargo", "Cambio_Area_Nomina",
    ]
    for c in columnas:
        if c not in comp.columns:
            comp[c] = ""
    return comp[columnas].sort_values(["Estado_Planta", "SAP"]).reset_index(drop=True)


def resumen_movimiento_planta(comparativo):
    ant = comparativo.dropna(subset=["Tipo_CECO_ANT"]).copy()
    act = comparativo.dropna(subset=["Tipo_CECO_ACT"]).copy()

    hc_ant = ant[ant["Tipo_CECO_ANT"].astype(str).ne("")].groupby("Tipo_CECO_ANT")["SAP"].nunique().rename("HC_Mes_Anterior")
    hc_act = act[act["Tipo_CECO_ACT"].astype(str).ne("")].groupby("Tipo_CECO_ACT")["SAP"].nunique().rename("HC_MD_Actual")
    nuevos = comparativo[comparativo["Estado_Planta"].eq("Nuevo en MD actual")].groupby("Tipo_CECO_ACT")["SAP"].nunique().rename("Nuevos")
    salidas = comparativo[comparativo["Estado_Planta"].eq("No está en MD actual")].groupby("Tipo_CECO_ANT")["SAP"].nunique().rename("Salidas")
    cambio_ceco = comparativo[comparativo["Cambio_CECO"].eq(True)].groupby("Tipo_CECO_ACT")["SAP"].nunique().rename("Cambios_CECO_Entrada")

    idx = sorted(set(hc_ant.index) | set(hc_act.index) | set(nuevos.index) | set(salidas.index) | set(cambio_ceco.index))
    res = pd.DataFrame(index=idx)
    res.index.name = "Tipo_CECO"
    for s in [hc_ant, hc_act, nuevos, salidas, cambio_ceco]:
        res = res.join(s, how="left")
    res = res.fillna(0).astype(int).reset_index()
    res["Variacion_HC"] = res["HC_MD_Actual"] - res["HC_Mes_Anterior"]
    return res

# ----------------------------
# Homologación y salidas
# ----------------------------

def homologar_base_cuentas(base_conceptos, matriz_dkon):
    homologada = base_conceptos.merge(
        matriz_dkon,
        on=["Concepto", "Tipo_CECO", "Llave_DKON"],
        how="left",
        suffixes=("", "_DKON")
    )

    homologada["Descripcion_Concepto"] = homologada["Descripcion_Concepto"].fillna("")
    mask_sin_desc = homologada["Descripcion_Concepto"].eq("")
    homologada.loc[mask_sin_desc, "Descripcion_Concepto"] = homologada.loc[mask_sin_desc, "Descripcion_Concepto_MD"]

    detalle_homologado = homologada[[
        "Periodo", "SAP", "Nombre", "Status", "Area_Nomina", "CECO", "Centro_Coste", "Tipo_CECO",
        "Cargo", "Nivel", "Division_Personal", "Regional", "Numero_ID", "Concepto", "Descripcion_Concepto",
        "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON",
        "Valor", "Fuente", "Llave_DKON"
    ]].copy()

    base_cuentas = (
        detalle_homologado
        .groupby([
            "Periodo", "SAP", "Nombre", "Status", "Area_Nomina", "CECO", "Centro_Coste", "Tipo_CECO",
            "Cargo", "Nivel", "Division_Personal", "Regional", "Numero_ID", "Cuenta_DKON", "Texto_Cuenta",
            "Grupo_DKON", "Descripcion_DKON", "Fuente"
        ], dropna=False)
        .agg(
            Valor=("Valor", "sum"),
            Conceptos_Agrupados=("Concepto", lambda s: ", ".join(sorted(set([str(x) for x in s if str(x) != ""]))))
        )
        .reset_index()
    )

    return detalle_homologado, base_cuentas


def construir_alertas(base_conceptos, detalle_homologado, comparativo):
    alertas = []

    def add_alert(df, tipo, detalle):
        if df.empty:
            return
        temp = df.copy()
        temp.insert(0, "Tipo_Alerta", tipo)
        temp.insert(1, "Detalle_Alerta", detalle)
        alertas.append(temp)

    add_alert(
        base_conceptos[base_conceptos["CECO"].eq("")][["SAP", "Nombre", "CECO", "Concepto", "Valor", "Fuente"]],
        "SAP sin CECO",
        "El empleado no tiene CECO para clasificar Tiendas/Logística/Admon."
    )
    add_alert(
        base_conceptos[base_conceptos["Tipo_CECO"].eq("Sin clasificar")][["SAP", "Nombre", "CECO", "Tipo_CECO", "Concepto", "Valor", "Fuente"]],
        "CECO sin clasificación",
        "El CECO no inicia por 101, 102 o 103."
    )
    add_alert(
        detalle_homologado[detalle_homologado["Cuenta_DKON"].isna() | detalle_homologado["Cuenta_DKON"].eq("")][[
            "SAP", "Nombre", "CECO", "Tipo_CECO", "Concepto", "Valor", "Fuente", "Llave_DKON"
        ]],
        "Concepto sin cuenta DKON",
        "No existe combinación Concepto + Tipo CECO en la matriz DKON."
    )
    add_alert(
        base_conceptos[base_conceptos["Valor"].isna()][["SAP", "Nombre", "CECO", "Concepto", "Valor", "Fuente"]],
        "Valor vacío",
        "El registro no trae valor numérico."
    )
    add_alert(
        comparativo[comparativo["Estado_Planta"].eq("No está en MD actual")][["SAP", "Nombre_ANT", "CECO_ANT", "Tipo_CECO_ANT", "Salario_Total_ANT"]],
        "Empleado del MD anterior no está en MD actual",
        "Puede representar retiro real, depuración de base o cambio no identificado."
    )
    add_alert(
        comparativo[comparativo["Estado_Planta"].eq("Nuevo en MD actual")][["SAP", "Nombre_ACT", "CECO_ACT", "Tipo_CECO_ACT", "Salario_Total_ACT"]],
        "Empleado nuevo en MD actual",
        "Puede representar ingreso real o empleado que no venía en la foto anterior."
    )

    if alertas:
        return pd.concat(alertas, ignore_index=True)
    return pd.DataFrame(columns=["Tipo_Alerta", "Detalle_Alerta"])


def resumenes(base_cuentas):
    resumen_tipo = (
        base_cuentas.groupby(["Tipo_CECO"], dropna=False)
        .agg(Valor=("Valor", "sum"), HC=("SAP", "nunique"))
        .reset_index()
        .sort_values("Valor", ascending=False)
    )
    resumen_cuenta = (
        base_cuentas.groupby(["Tipo_CECO", "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON"], dropna=False)
        .agg(Valor=("Valor", "sum"), HC=("SAP", "nunique"))
        .reset_index()
        .sort_values(["Tipo_CECO", "Cuenta_DKON"])
    )
    resumen_ceco = (
        base_cuentas.groupby(["Tipo_CECO", "CECO", "Centro_Coste"], dropna=False)
        .agg(Valor=("Valor", "sum"), HC=("SAP", "nunique"))
        .reset_index()
        .sort_values(["Tipo_CECO", "CECO"])
    )
    return resumen_tipo, resumen_cuenta, resumen_ceco


def to_excel_bytes(sheets: dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        header_fmt = workbook.add_format({
            "bold": True,
            "font_color": "white",
            "bg_color": "#F97316",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })
        money_fmt = workbook.add_format({"num_format": "#,##0", "border": 1})
        text_fmt = workbook.add_format({"border": 1})
        warn_fmt = workbook.add_format({"bg_color": "#FEF3C7", "border": 1})

        for name, df in sheets.items():
            safe_name = name[:31]
            df.to_excel(writer, index=False, sheet_name=safe_name)
            ws = writer.sheets[safe_name]
            ws.freeze_panes(1, 0)
            for col_num, value in enumerate(df.columns.values):
                ws.write(0, col_num, value, header_fmt)
                width = min(max(len(str(value)) + 2, 12), 35)
                if len(df) > 0:
                    sample = df[value].astype(str).head(100).map(len).max()
                    width = min(max(width, int(sample) + 2), 45)
                ws.set_column(col_num, col_num, width, text_fmt)
                if value.lower() in ["valor", "hc"] or "valor" in value.lower() or "salario" in value.lower() or "diferencia" in value.lower():
                    ws.set_column(col_num, col_num, 16, money_fmt)
            if "ALERTA" in safe_name.upper():
                ws.set_tab_color("#DC2626")
                ws.conditional_format(1, 0, max(len(df), 1), max(len(df.columns) - 1, 0), {
                    "type": "no_errors",
                    "format": warn_fmt,
                })
            elif "COMPARATIVO" in safe_name.upper() or "MOVIMIENTO" in safe_name.upper():
                ws.set_tab_color("#2563EB")
            else:
                ws.set_tab_color("#F97316")
    output.seek(0)
    return output.getvalue()

# ----------------------------
# Interfaz
# ----------------------------

st.title("🦜 Proyección de Costos JMC - MVP 2")
st.caption("Motor inicial: DKON + MD anterior + MD actual + conceptos Y")

with st.expander("📌 ¿Qué hace esta versión?", expanded=True):
    st.markdown(
        """
        Esta versión construye la base mínima del modelo financiero y agrega el comparativo de planta:

        1. Lee **Dkon** y crea la matriz `Concepto Y + Tipo CECO = Cuenta DKON`.
        2. Lee **MD Mes Anterior** y **MD Actual**.
        3. Clasifica CECO por prefijo:
           - `101` = Tiendas
           - `102` = Logística / CEDIS
           - `103` = Admon
        4. Genera el detalle por concepto `Y` del MD actual.
        5. Homologa cada concepto a cuenta DKON.
        6. Genera comparativo de planta: nuevos, salidas, cambios de salario, CECO, cargo y área nómina.
        """
    )

periodo = st.text_input("Periodo de proyección", value=datetime.today().strftime("%Y-%m"))

col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    dkon_file = st.file_uploader("1. Cargar Dkon.XLSX", type=["xlsx", "xlsm", "xls"])
with col2:
    md_ant_file = st.file_uploader("2. Cargar MD Mes Anterior", type=["xlsx", "xlsm", "xls"])
with col3:
    md_act_file = st.file_uploader("3. Cargar MD Actual", type=["xlsx", "xlsm", "xls"])

procesar = st.button("🚀 Generar base MVP 2")

if procesar:
    if dkon_file is None or md_ant_file is None or md_act_file is None:
        st.error("Debes cargar Dkon, MD Mes Anterior y MD Actual.")
        st.stop()

    try:
        with st.spinner("Leyendo Dkon y construyendo matriz de homologación..."):
            matriz_dkon = construir_matriz_dkon(dkon_file)

        with st.spinner("Leyendo MD Mes Anterior y MD Actual para comparativo de planta..."):
            md_ant_dim = leer_md_dimension(md_ant_file, etiqueta="Mes anterior")
            md_act_dim = leer_md_dimension(md_act_file, etiqueta="Actual")
            comparativo = construir_comparativo_md(md_ant_dim, md_act_dim)
            res_mov = resumen_movimiento_planta(comparativo)

        with st.spinner("Leyendo MD Actual y normalizando conceptos Y..."):
            md_conceptos = leer_md_conceptos(md_act_file, fuente="MD Actual")
            base_conceptos = crear_base_conceptos(md_conceptos, periodo)

        with st.spinner("Homologando conceptos contra cuenta DKON..."):
            detalle_homologado, base_cuentas = homologar_base_cuentas(base_conceptos, matriz_dkon)
            resumen_tipo, resumen_cuenta, resumen_ceco = resumenes(base_cuentas)
            alertas = construir_alertas(base_conceptos, detalle_homologado, comparativo)

        total_valor = base_cuentas["Valor"].sum() if not base_cuentas.empty else 0
        total_hc = base_cuentas["SAP"].nunique() if not base_cuentas.empty else 0
        sin_cuenta = detalle_homologado["Cuenta_DKON"].isna().sum() + detalle_homologado["Cuenta_DKON"].eq("").sum()
        nuevos = int((comparativo["Estado_Planta"] == "Nuevo en MD actual").sum())
        salidas = int((comparativo["Estado_Planta"] == "No está en MD actual").sum())

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Conceptos Y en Dkon", f"{matriz_dkon['Concepto'].nunique():,}")
        m2.metric("Registros detalle", f"{len(detalle_homologado):,}")
        m3.metric("HC MD Actual", f"{total_hc:,}")
        m4.metric("Nuevos", f"{nuevos:,}")
        m5.metric("Salidas", f"{salidas:,}")

        st.subheader("Vista previa - Base por cuenta DKON")
        st.dataframe(base_cuentas.head(100), use_container_width=True)

        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "Resumen Tipo", "Resumen Cuenta", "Resumen CECO", "Mov. Planta", "Comparativo MD", "Detalle Conceptos", "Alertas"
        ])
        with tab1:
            st.dataframe(resumen_tipo, use_container_width=True)
        with tab2:
            st.dataframe(resumen_cuenta, use_container_width=True)
        with tab3:
            st.dataframe(resumen_ceco, use_container_width=True)
        with tab4:
            st.dataframe(res_mov, use_container_width=True)
        with tab5:
            st.dataframe(comparativo.head(1000), use_container_width=True)
        with tab6:
            st.dataframe(detalle_homologado.head(1000), use_container_width=True)
        with tab7:
            st.dataframe(alertas.head(1000), use_container_width=True)

        sheets = {
            "MATRIZ_DKON_Y": matriz_dkon,
            "MD_ANT_NORMALIZADO": md_ant_dim,
            "MD_ACT_NORMALIZADO": md_act_dim,
            "COMPARATIVO_MD": comparativo,
            "RESUMEN_MOV_PLANTA": res_mov,
            "BASE_CONCEPTOS_Y": detalle_homologado,
            "BASE_CUENTAS_DKON": base_cuentas,
            "RESUMEN_TIPO_CECO": resumen_tipo,
            "RESUMEN_CUENTA": resumen_cuenta,
            "RESUMEN_CECO": resumen_ceco,
            "ALERTAS": alertas,
        }
        excel_bytes = to_excel_bytes(sheets)
        st.download_button(
            "⬇️ Descargar base de proyección MVP 2",
            data=excel_bytes,
            file_name=f"Base_Proyeccion_Costos_MVP2_{periodo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.success("Base generada correctamente. Valida COMPARATIVO_MD, BASE_CONCEPTOS_Y y BASE_CUENTAS_DKON.")

    except Exception as e:
        st.exception(e)
        st.error("No se pudo generar la base. Revisa si los archivos tienen las hojas/columnas esperadas.")

st.markdown("---")
st.caption("Creado por Andrés Huérfano Dávila - Nómina JMC")
