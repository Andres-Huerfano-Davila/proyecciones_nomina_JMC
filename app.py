import io
import re
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

# =====================================================
# PROYECCIÓN COSTOS - MVP 1
# Motor base: DKON + MD Actual -> Base concepto Y + Base cuenta
# Creado para estructurar costo de personal por empleado, concepto, CECO y cuenta financiera.
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
    # Evita que códigos enteros salgan como 60000001.0
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
    """Convierte valores como '1.750.905', '1,750,905', '$ 1.750.905' a número."""
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace("$", "").replace("COP", "").replace(" ", "")
    # Si viene con formato colombiano: 1.750.905,50
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s and "," not in s:
        # Si todos los grupos después del punto tienen 3 dígitos, son miles
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
    xls = pd.ExcelFile(uploaded_file)
    norm_map = {norm_col(s): s for s in xls.sheet_names}
    for name in preferred_names:
        n = norm_col(name)
        if n in norm_map:
            return norm_map[n]
    return xls.sheet_names[0]


def read_excel_any(uploaded_file, preferred_sheet=None, dtype=str):
    uploaded_file.seek(0)
    if preferred_sheet:
        sheet = find_sheet_name(uploaded_file, [preferred_sheet])
    else:
        sheet = 0
    uploaded_file.seek(0)
    return pd.read_excel(uploaded_file, sheet_name=sheet, dtype=dtype)


def pick_col(df, candidates, required=True):
    """Busca una columna por candidatos aproximados normalizados."""
    col_map = {norm_col(c): c for c in df.columns}
    for cand in candidates:
        n = norm_col(cand)
        if n in col_map:
            return col_map[n]
    # búsqueda parcial
    for cand in candidates:
        n = norm_col(cand)
        for k, v in col_map.items():
            if n and n in k:
                return v
    if required:
        raise ValueError(f"No encontré columna requerida. Candidatas: {candidates}")
    return None

# ----------------------------
# DKON
# ----------------------------

def construir_matriz_dkon(dkon_file):
    dkon_file.seek(0)
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

    matriz["Descripcion_Concepto"] = matriz[col_texto_concepto] if col_texto_concepto else ""
    matriz["Texto_Cuenta"] = matriz[col_texto_cuenta] if col_texto_cuenta else ""
    matriz["Grupo_DKON"] = matriz[col_grupo] if col_grupo else ""
    matriz["Descripcion_DKON"] = matriz[col_descripcion] if col_descripcion else ""

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

    # Hay duplicados naturales por Administrativos/Ejecutivos que terminan en la misma cuenta 63.
    matriz = matriz.drop_duplicates(subset=["Concepto", "Tipo_CECO"], keep="first")
    matriz["Llave_DKON"] = matriz["Tipo_CECO"] + "|" + matriz["Concepto"]

    return matriz.sort_values(["Concepto", "Tipo_CECO"]).reset_index(drop=True)

# ----------------------------
# MD Actual
# ----------------------------

def leer_md_normalizado(md_file):
    md_file.seek(0)
    # Preferimos Salario_Bono_Vigente porque trae cada concepto Y con importe.
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
    col_salario_total = pick_col(df, ["Salario Total", "Salario_total"], required=False)
    col_nivel = pick_col(df, ["Gr.prof.", "Gr prof", "Nivel"], required=False)
    col_division = pick_col(df, ["División de personal", "Division de personal"], required=False)
    col_regional = pick_col(df, ["Encargado para registro de tie", "Regional"], required=False)

    out = pd.DataFrame()
    out["SAP"] = df[col_sap].map(clean_code)
    out["Nombre"] = df[col_nombre].fillna("").astype(str).str.strip() if col_nombre else ""
    out["Status"] = df[col_status].fillna("").astype(str).str.strip() if col_status else ""
    out["Area_Nomina"] = df[col_area_nomina].fillna("").astype(str).str.strip() if col_area_nomina else ""
    out["CECO"] = df[col_ceco].map(clean_ceco)
    out["Centro_Coste"] = df[col_centro].fillna("").astype(str).str.strip() if col_centro else ""
    out["Tipo_CECO"] = out["CECO"].map(clasificar_tipo_ceco)
    out["Cargo"] = df[col_funcion].fillna("").astype(str).str.strip() if col_funcion else ""
    out["Nivel"] = df[col_nivel].fillna("").astype(str).str.strip() if col_nivel else ""
    out["Division_Personal"] = df[col_division].fillna("").astype(str).str.strip() if col_division else ""
    out["Regional"] = df[col_regional].fillna("").astype(str).str.strip() if col_regional else ""
    out["Concepto"] = df[col_concepto].map(clean_code)
    out["Descripcion_Concepto_MD"] = df[col_desc_concepto].fillna("").astype(str).str.strip() if col_desc_concepto else ""
    if col_importe:
        out["Valor"] = df[col_importe].map(to_number)
    elif col_salario_total:
        out["Valor"] = df[col_salario_total].map(to_number)
    else:
        out["Valor"] = 0.0

    # Solo conceptos Y.
    out = out[out["Concepto"].str.startswith("Y", na=False)].copy()
    out = out[out["SAP"].ne("")].copy()

    return out.reset_index(drop=True)


def crear_base_conceptos(md_norm, periodo, fuente="MD Actual"):
    base = md_norm.copy()
    base.insert(0, "Periodo", periodo)
    base["Fuente"] = fuente
    base["Llave_DKON"] = base["Tipo_CECO"] + "|" + base["Concepto"]
    cols = [
        "Periodo", "SAP", "Nombre", "Status", "Area_Nomina", "CECO", "Centro_Coste", "Tipo_CECO",
        "Cargo", "Nivel", "Division_Personal", "Regional", "Concepto", "Descripcion_Concepto_MD",
        "Valor", "Fuente", "Llave_DKON"
    ]
    return base[cols].copy()


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
        "Cargo", "Nivel", "Division_Personal", "Regional", "Concepto", "Descripcion_Concepto",
        "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON",
        "Valor", "Fuente", "Llave_DKON"
    ]].copy()

    # Base financiera por empleado + cuenta. Conserva lista de conceptos que suman a la cuenta.
    base_cuentas = (
        detalle_homologado
        .groupby([
            "Periodo", "SAP", "Nombre", "Status", "Area_Nomina", "CECO", "Centro_Coste", "Tipo_CECO",
            "Cargo", "Nivel", "Division_Personal", "Regional", "Cuenta_DKON", "Texto_Cuenta",
            "Grupo_DKON", "Descripcion_DKON", "Fuente"
        ], dropna=False)
        .agg(
            Valor=("Valor", "sum"),
            Conceptos_Agrupados=("Concepto", lambda s: ", ".join(sorted(set([str(x) for x in s if str(x) != ""]))))
        )
        .reset_index()
    )

    return detalle_homologado, base_cuentas


def construir_alertas(base_conceptos, detalle_homologado):
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

    dup = base_conceptos[base_conceptos.duplicated(subset=["SAP", "Concepto", "Fuente"], keep=False)].copy()
    add_alert(
        dup[["SAP", "Nombre", "CECO", "Tipo_CECO", "Concepto", "Valor", "Fuente"]],
        "Duplicado SAP + concepto + fuente",
        "Puede ser válido si hay varios registros vigentes, pero debe revisarse."
    )

    if alertas:
        return pd.concat(alertas, ignore_index=True)
    return pd.DataFrame(columns=["Tipo_Alerta", "Detalle_Alerta", "SAP", "Nombre", "CECO", "Tipo_CECO", "Concepto", "Valor", "Fuente"])


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
                if value.lower() in ["valor", "hc"] or "valor" in value.lower():
                    ws.set_column(col_num, col_num, 16, money_fmt)
            if "ALERTAS" in safe_name.upper():
                ws.set_tab_color("#DC2626")
                ws.conditional_format(1, 0, max(len(df), 1), max(len(df.columns) - 1, 0), {
                    "type": "no_errors",
                    "format": warn_fmt,
                })
            else:
                ws.set_tab_color("#F97316")
    output.seek(0)
    return output.getvalue()

# ----------------------------
# Interfaz
# ----------------------------

st.title("🦜 Proyección de Costos JMC - MVP 1")
st.caption("Motor inicial: conceptos Y + tipo de CECO + cuenta DKON")

with st.expander("📌 ¿Qué hace esta primera versión?", expanded=True):
    st.markdown(
        """
        Esta versión construye la base mínima del modelo financiero:

        1. Lee **Dkon** y crea la matriz `Concepto Y + Tipo CECO = Cuenta DKON`.
        2. Lee el **MD Actual** y clasifica el CECO del empleado:
           - `101` = Tiendas
           - `102` = Logística / CEDIS
           - `103` = Admon
        3. Genera el detalle por concepto `Y`.
        4. Homologa cada concepto a cuenta DKON.
        5. Entrega una base lista para Power Query / Power Pivot.
        """
    )

col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    periodo = st.text_input("Periodo de proyección", value=datetime.today().strftime("%Y-%m"))
with col2:
    dkon_file = st.file_uploader("1. Cargar Dkon.XLSX", type=["xlsx", "xlsm", "xls"])
with col3:
    md_file = st.file_uploader("2. Cargar MD_ACTUAL.xlsx", type=["xlsx", "xlsm", "xls"])

procesar = st.button("🚀 Generar base MVP")

if procesar:
    if dkon_file is None or md_file is None:
        st.error("Debes cargar mínimo Dkon y MD Actual.")
        st.stop()

    try:
        with st.spinner("Leyendo Dkon y construyendo matriz de homologación..."):
            matriz_dkon = construir_matriz_dkon(dkon_file)

        with st.spinner("Leyendo MD Actual y normalizando conceptos Y..."):
            md_norm = leer_md_normalizado(md_file)
            base_conceptos = crear_base_conceptos(md_norm, periodo, fuente="MD Actual")

        with st.spinner("Homologando conceptos contra cuenta DKON..."):
            detalle_homologado, base_cuentas = homologar_base_cuentas(base_conceptos, matriz_dkon)
            alertas = construir_alertas(base_conceptos, detalle_homologado)
            resumen_tipo, resumen_cuenta, resumen_ceco = resumenes(base_cuentas)

        total_valor = base_cuentas["Valor"].sum() if not base_cuentas.empty else 0
        total_hc = base_cuentas["SAP"].nunique() if not base_cuentas.empty else 0
        sin_cuenta = detalle_homologado["Cuenta_DKON"].isna().sum() + detalle_homologado["Cuenta_DKON"].eq("").sum()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Conceptos Y en Dkon", f"{matriz_dkon['Concepto'].nunique():,}")
        m2.metric("Registros detalle", f"{len(detalle_homologado):,}")
        m3.metric("HC", f"{total_hc:,}")
        m4.metric("Sin cuenta DKON", f"{int(sin_cuenta):,}")

        st.subheader("Vista previa - Base por cuenta")
        st.dataframe(base_cuentas.head(100), use_container_width=True)

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "Resumen Tipo", "Resumen Cuenta", "Resumen CECO", "Detalle Conceptos", "Alertas"
        ])
        with tab1:
            st.dataframe(resumen_tipo, use_container_width=True)
        with tab2:
            st.dataframe(resumen_cuenta, use_container_width=True)
        with tab3:
            st.dataframe(resumen_ceco, use_container_width=True)
        with tab4:
            st.dataframe(detalle_homologado.head(500), use_container_width=True)
        with tab5:
            st.dataframe(alertas.head(500), use_container_width=True)

        sheets = {
            "MATRIZ_DKON_Y": matriz_dkon,
            "MD_NORMALIZADO_Y": md_norm,
            "BASE_CONCEPTOS_Y": detalle_homologado,
            "BASE_CUENTAS_DKON": base_cuentas,
            "RESUMEN_TIPO_CECO": resumen_tipo,
            "RESUMEN_CUENTA": resumen_cuenta,
            "RESUMEN_CECO": resumen_ceco,
            "ALERTAS": alertas,
        }
        excel_bytes = to_excel_bytes(sheets)
        st.download_button(
            "⬇️ Descargar base de proyección MVP",
            data=excel_bytes,
            file_name=f"Base_Proyeccion_Costos_MVP_{periodo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.success("Base generada correctamente. Valida primero BASE_CONCEPTOS_Y y BASE_CUENTAS_DKON.")

    except Exception as e:
        st.exception(e)
        st.error("No se pudo generar la base. Revisa si los archivos tienen las hojas/columnas esperadas.")

st.markdown("---")
st.caption("Creado por Andrés Huérfano Dávila - Nómina JMC")
