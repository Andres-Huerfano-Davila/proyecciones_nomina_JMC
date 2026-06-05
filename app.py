import io
import re
import unicodedata
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

APP_TITLE = "Modelo proyecciones nómina JMC V5"
DEFAULT_SMMLV = 1_750_905
DEFAULT_AUX_TRANSPORTE = 249_095

TIPO_CECO_BY_PREFIX_3 = {"101": "Tiendas", "102": "Logística", "103": "Admon"}
TIPO_CECO_BY_ACCOUNT_PREFIX = {"60": "Tiendas", "62": "Logística", "63": "Admon"}
BASIC_SALARY_CONCEPTS = {"Y010", "Y011", "Y020", "Y050", "Y051", "Y090"}
AUX_TRANSPORTE_CONCEPT = "Y200"
HOUR_CONCEPTS = {"Y220", "Y221", "Y300", "Y305", "Y310", "Y315", "Y350", "YM01"}
HOUR_DAY_TYPE = {"Y220": "HABILES", "Y300": "HABILES", "Y305": "HABILES", "Y221": "DOM_FEST", "Y310": "DOM_FEST", "Y315": "DOM_FEST", "Y350": "DOM_FEST", "YM01": "DOM_FEST"}
AUX_ELIGIBLE_DESCRIPTIONS = {"sueldo basico", "salario part time dias", "salario part-time dias", "salario parti-time dias", "salario part time horas", "salario part-time horas", "apoyo sostenimiento", "apoyo sostenimiento pract"}

# ============================================================
# Utilidades
# ============================================================
def strip_accents(text: str) -> str:
    text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))

def norm_text(x) -> str:
    return re.sub(r"\s+", " ", strip_accents(x).lower().strip())

def norm_col(x) -> str:
    x = norm_text(x).replace(".", "").replace("/", " ").replace("-", " ")
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", x)).strip("_")

def norm_key(x) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm_text(x))

def find_col(df: pd.DataFrame, candidates: List[str], required=False) -> Optional[str]:
    norm_map = {norm_col(c): c for c in df.columns}
    cands = [norm_col(c) for c in candidates]
    for c in cands:
        if c in norm_map:
            return norm_map[c]
    for original in df.columns:
        n = norm_col(original)
        for c in cands:
            if c and (c in n or n in c):
                return original
    if required:
        raise ValueError(f"No encontré columna para: {candidates}")
    return None

def to_number(x) -> float:
    if pd.isna(x): return 0.0
    if isinstance(x, (int, float, np.integer, np.floating)): return float(x)
    s = str(x).strip().replace("$", "").replace("COP", "").replace(" ", "").replace("\u00a0", "")
    if not s: return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s and all(len(p) == 3 for p in s.split(".")[1:]):
        s = s.replace(".", "")
    try:
        val = float(s)
        return -val if neg else val
    except Exception:
        return 0.0

def to_sap(x) -> str:
    if pd.isna(x): return ""
    s = str(x).strip()
    if s.endswith(".0"): s = s[:-2]
    return re.sub(r"\D", "", s)

def to_concept(x) -> str:
    if pd.isna(x): return ""
    return str(x).strip().upper().replace(" ", "")

def to_ceco(x) -> str:
    if pd.isna(x): return ""
    s = str(x).strip()
    if s.endswith(".0"): s = s[:-2]
    return re.sub(r"\D", "", s)

def classify_ceco(ceco) -> str:
    return TIPO_CECO_BY_PREFIX_3.get(to_ceco(ceco)[:3], "Sin clasificar")

def to_datetime_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", dayfirst=True).dt.normalize()

def yes_no(x, default=False) -> bool:
    if pd.isna(x): return default
    s = norm_text(x)
    if s in ["si", "sí", "s", "x", "1", "true", "verdadero", "yes"]: return True
    if s in ["no", "n", "0", "false", "falso"]: return False
    return default

def inclusive_days(start, end) -> int:
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start: return 0
    return int((end - start).days) + 1

def days360_us(start, end) -> int:
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start: return 0
    d1, d2 = min(start.day, 30), end.day
    if d1 == 30 and d2 == 31: d2 = 30
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)

def working_days_mon_fri(start, end) -> int:
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start: return 0
    days = pd.date_range(start, end, freq="D")
    return int(sum(d.weekday() < 5 for d in days))

def weekend_days(start, end) -> int:
    if start is None or end is None or pd.isna(start) or pd.isna(end) or end < start: return 0
    days = pd.date_range(start, end, freq="D")
    return int(sum(d.weekday() >= 5 for d in days))

def calculate_paid_days(area_nomina: str, fecha_inicio, fecha_retiro, periodo_ini, periodo_fin, dias_aus) -> Tuple[float, str]:
    area = norm_text(area_nomina)
    start = max(fecha_inicio if fecha_inicio is not None and not pd.isna(fecha_inicio) else periodo_ini, periodo_ini)
    end = periodo_fin
    if fecha_retiro is not None and not pd.isna(fecha_retiro) and fecha_retiro.year < 9999:
        end = min(fecha_retiro, periodo_fin)
    if end < start: return 0.0, "Sin días en periodo"
    if "parcial" in area and "hora" in area:
        base, method = working_days_mon_fri(start, end), "Part time hora: lunes-viernes"
    elif "parcial" in area and "dia" in area:
        base, method = weekend_days(start, end), "Part time día: sábados-domingos"
    elif "365" in area:
        base, method = inclusive_days(start, end), "ZL / 365: calendario"
    else:
        base, method = days360_us(start, end + pd.Timedelta(days=1)), "ZM / 360: DAYS360"
    return max(float(base) - float(dias_aus or 0), 0), method

def safe_sheet_names(file) -> List[str]:
    try:
        file.seek(0); return pd.ExcelFile(file).sheet_names
    except Exception:
        return []

def read_sheet(file, preferred=None, header=0) -> pd.DataFrame:
    sheets = safe_sheet_names(file)
    sheet = preferred if preferred in sheets else (sheets[0] if sheets else 0)
    file.seek(0)
    return pd.read_excel(file, sheet_name=sheet, header=header, dtype=str)

def detect_header_row(file, sheet, terms, max_rows=15) -> int:
    file.seek(0)
    raw = pd.read_excel(file, sheet_name=sheet, header=None, nrows=max_rows, dtype=str)
    terms = [norm_text(t) for t in terms]
    best, score = 0, -1
    for idx, row in raw.iterrows():
        joined = " | ".join(norm_text(v) for v in row.tolist() if pd.notna(v))
        s = sum(t in joined for t in terms)
        if s > score: best, score = idx, s
    return int(best)

# ============================================================
# Calendario simple para horas proyectadas
# ============================================================
def easter_date(year: int) -> date:
    a=year%19; b=year//100; c=year%100; d=b//4; e=b%4; f=(b+8)//25; g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30; i=c//4; k=c%4; l=(32+2*e+2*i-h-k)%7; m=(a+11*h+22*l)//451
    month=(h+l-7*m+114)//31; day=((h+l-7*m+114)%31)+1
    return date(year, month, day)

def move_monday(d: date) -> date:
    return (pd.Timestamp(d) + pd.Timedelta(days=(7 - pd.Timestamp(d).weekday()) % 7)).date()

def colombia_holidays(year: int) -> set:
    hol = {date(year,1,1), date(year,5,1), date(year,7,20), date(year,8,7), date(year,12,8), date(year,12,25)}
    for d in [date(year,1,6), date(year,3,19), date(year,6,29), date(year,8,15), date(year,10,12), date(year,11,1), date(year,11,11)]: hol.add(move_monday(d))
    easter = pd.Timestamp(easter_date(year))
    for off in [-3, -2, 43, 64, 71]:
        d = (easter + pd.Timedelta(days=off)).date()
        hol.add(move_monday(d) if off > 0 else d)
    return hol

def count_days_for_hours(year, month, day_type) -> int:
    ini = pd.Timestamp(date(year, month, 1)); fin = ini + pd.offsets.MonthEnd(0)
    hol = colombia_holidays(year); days = pd.date_range(ini, fin, freq="D")
    if day_type == "DOM_FEST": return int(sum(d.weekday() == 6 or d.date() in hol for d in days))
    if day_type == "HABILES": return int(sum(d.weekday() < 6 and d.date() not in hol for d in days))
    return len(days)

# ============================================================
# Lectores principales
# ============================================================
def build_dkon_matrix(file) -> pd.DataFrame:
    sheets = safe_sheet_names(file); sheet = "Sheet1" if "Sheet1" in sheets else sheets[0]
    df = read_sheet(file, sheet)
    c_con = find_col(df, ["CC-nómina", "CC nomina", "CC-nomina"], True)
    c_txt = find_col(df, ["Txt.CC-nóm.", "Texto CC nomina", "Texto concepto"])
    c_acc = find_col(df, ["Cta.mayor", "Cta mayor", "Cuenta mayor"], True)
    c_acc_txt = find_col(df, ["Texto breve", "Texto cuenta"])
    c_group = find_col(df, ["CUENTA", "Grupo", "Grupo de cuentas"])
    c_desc = find_col(df, ["Descripcion ", "Descripción", "Descripcion"])
    out = pd.DataFrame()
    out["Concepto"] = df[c_con].map(to_concept)
    out["Cuenta_DKON"] = df[c_acc].map(to_ceco)
    out = out[out["Concepto"].str.startswith("Y", na=False) & out["Cuenta_DKON"].str[:2].isin(["60","62","63"])].copy()
    out["Tipo_CECO"] = out["Cuenta_DKON"].str[:2].map(TIPO_CECO_BY_ACCOUNT_PREFIX)
    out["Texto_Concepto_DKON"] = df.loc[out.index, c_txt].fillna("") if c_txt else ""
    out["Texto_Cuenta"] = df.loc[out.index, c_acc_txt].fillna("") if c_acc_txt else ""
    out["Grupo_DKON"] = df.loc[out.index, c_group].fillna("") if c_group else ""
    out["Descripcion_DKON"] = df.loc[out.index, c_desc].fillna("") if c_desc else ""
    return out.drop_duplicates().sort_values(["Concepto","Tipo_CECO","Cuenta_DKON"]).drop_duplicates(["Concepto","Tipo_CECO"], keep="first").reset_index(drop=True)

def read_md_dimension(file) -> pd.DataFrame:
    sheets = safe_sheet_names(file); sheet = "Consolidado__Base" if "Consolidado__Base" in sheets else sheets[0]
    df = read_sheet(file, sheet)
    c_sap = find_col(df, ["Nº pers.", "N° pers.", "SAP", "Número personal"], True)
    c_name = find_col(df, ["Número de personal", "Nombre", "Empleado"], True)
    c_area = find_col(df, ["Área de nómina", "Area de nomina"], True)
    c_ceco = find_col(df, ["Ce.coste", "Ce coste", "CECO"], True)
    c_centro = find_col(df, ["Centro de coste", "Centro de costo"])
    c_cargo = find_col(df, ["Función_2", "Funcion_2", "Función", "Funcion", "Cargo"])
    c_nivel = find_col(df, ["Gr.prof.", "Gr prof", "Nivel"])
    c_sal = find_col(df, ["Salario Total", "Importe", "Salario"])
    c_ing = find_col(df, ["Fecha", "Fecha alta", "Fecha de alta", "Fecha ingreso", "Fecha de ingreso"])
    c_ret = find_col(df, ["Baja", "Fecha de baja", "Fecha retiro"])
    c_tipo = find_col(df, ["CC-nómina_2", "CC nomina_2", "Tipo Salario", "Texto CC nómina"])
    c_con = find_col(df, ["CC-nómina", "CC nomina"])
    out = pd.DataFrame()
    out["SAP"] = df[c_sap].map(to_sap); out["Nombre"] = df[c_name].fillna("").astype(str).str.strip()
    out["Area_Nomina"] = df[c_area].fillna("").astype(str).str.strip(); out["CECO"] = df[c_ceco].map(to_ceco)
    out["Tipo_CECO"] = out["CECO"].map(classify_ceco)
    out["Centro_Coste"] = df[c_centro].fillna("").astype(str).str.strip() if c_centro else ""
    out["Cargo"] = df[c_cargo].fillna("").astype(str).str.strip() if c_cargo else ""; out["Cargo_Key"] = out["Cargo"].map(norm_key)
    out["Nivel"] = df[c_nivel].fillna("").astype(str).str.strip() if c_nivel else ""
    out["Salario_Total_MD"] = df[c_sal].map(to_number) if c_sal else 0.0
    out["Fecha_Ingreso"] = to_datetime_series(df[c_ing]) if c_ing else pd.NaT
    out["Fecha_Retiro"] = to_datetime_series(df[c_ret]) if c_ret else pd.NaT
    out["Tipo_Salario"] = df[c_tipo].fillna("").astype(str).str.strip() if c_tipo else ""
    out["Concepto_Salario_MD"] = df[c_con].map(to_concept) if c_con else ""
    out["Fuente_Empleado"] = "MD actual"
    return out[out["SAP"] != ""].drop_duplicates("SAP", keep="first").reset_index(drop=True)

def read_md_active_concepts(file) -> pd.DataFrame:
    sheets = safe_sheet_names(file); sheet = "Salario_Bono_Vigente" if "Salario_Bono_Vigente" in sheets else ("Consolidado__Base" if "Consolidado__Base" in sheets else sheets[0])
    df = read_sheet(file, sheet)
    c_sap = find_col(df, ["Nº pers.", "N° pers.", "SAP", "Número personal"], True)
    c_con = find_col(df, ["CC-nómina", "CC nomina", "CC-nomina"], True)
    c_txt = find_col(df, ["CC-nómina_2", "CC nomina_2", "Texto concepto", "Txt.CC-nóm."])
    c_val = find_col(df, ["Importe", "Salario Total", "Valor", "Salario"], True)
    c_desde = find_col(df, ["Desde", "Fecha desde"]); c_hasta = find_col(df, ["Hasta", "Fecha hasta"])
    out = pd.DataFrame()
    out["SAP"] = df[c_sap].map(to_sap); out["Concepto"] = df[c_con].map(to_concept)
    out["Texto_Concepto"] = df[c_txt].fillna("").astype(str).str.strip() if c_txt else ""
    out["Importe_Mensual"] = df[c_val].map(to_number)
    out["Desde"] = to_datetime_series(df[c_desde]) if c_desde else pd.NaT; out["Hasta"] = to_datetime_series(df[c_hasta]) if c_hasta else pd.NaT
    out = out[(out["SAP"] != "") & out["Concepto"].isin(BASIC_SALARY_CONCEPTS) & (out["Importe_Mensual"] != 0)].copy()
    if c_hasta: out = out[out["Hasta"].isna() | (out["Hasta"].dt.year >= 9999)]
    return out.reset_index(drop=True)

# ============================================================
# Reglas de conceptos
# ============================================================
def default_rules(dkon: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in sorted(dkon["Concepto"].dropna().unique()):
        if c in BASIC_SALARY_CONCEPTS:
            regla, ibc, prima, ces, vac, exo, mod = "PROPORCIONAL_DIAS", True, True, True, True, True, True
        elif c == AUX_TRANSPORTE_CONCEPT:
            regla, ibc, prima, ces, vac, exo, mod = "PROPORCIONAL_DIAS", False, True, True, False, True, False
        elif c in HOUR_CONCEPTS:
            regla, ibc, prima, ces, vac, exo, mod = "NETO", True, True, True, False, True, False
        else:
            regla, ibc, prima, ces, vac, exo, mod = "NETO", False, False, False, False, True, False
        rows.append({"Concepto": c, "Regla_Calculo": regla, "Base_IBC": ibc, "Base_Prima": prima, "Base_Cesantias": ces, "Base_Vacaciones": vac, "Base_Exoneracion": exo, "Modifica_Salario": mod, "Regla_Origen": "Default"})
    return pd.DataFrame(rows)

def read_rules(file, dkon):
    base = default_rules(dkon)
    if file is None: return base
    df = read_sheet(file)
    c_con = find_col(df, ["Concepto", "CC-nómina", "CC nomina"], True)
    c_reg = find_col(df, ["Regla cálculo", "Regla_Calculo", "Regla"])
    cols = {"Base_IBC": find_col(df, ["Base IBC", "Base SS", "IBC"]), "Base_Prima": find_col(df, ["Base Prima"]), "Base_Cesantias": find_col(df, ["Base Cesantías", "Base Cesantias"]), "Base_Vacaciones": find_col(df, ["Base Vacaciones"]), "Base_Exoneracion": find_col(df, ["Base Exoneración", "Base Exoneracion"]), "Modifica_Salario": find_col(df, ["Modifica salario"])}
    custom = pd.DataFrame({"Concepto": df[c_con].map(to_concept)})
    custom["Regla_Calculo"] = df[c_reg].fillna("NETO").astype(str).str.upper().str.strip() if c_reg else "NETO"
    for col, src in cols.items(): custom[col] = df[src].map(lambda x: yes_no(x, False if col != "Base_Exoneracion" else True)) if src else (True if col == "Base_Exoneracion" else False)
    custom["Regla_Origen"] = "Usuario"; custom = custom[custom["Concepto"] != ""].drop_duplicates("Concepto", keep="last")
    out = pd.concat([base[~base["Concepto"].isin(custom["Concepto"])], custom], ignore_index=True)
    return out

def add_rule_flags(base, rules):
    if base.empty: return base
    out = base.merge(rules, on="Concepto", how="left")
    for c in ["Base_IBC","Base_Prima","Base_Cesantias","Base_Vacaciones","Base_Exoneracion","Modifica_Salario"]: out[c] = out[c].fillna(False).astype(bool)
    out["Regla_Calculo"] = out["Regla_Calculo"].fillna("SIN_REGLA"); out["Regla_Origen"] = out["Regla_Origen"].fillna("Sin regla")
    return out

# ============================================================
# Lectores de novedades
# ============================================================
def read_absences(file):
    if file is None: return pd.DataFrame(columns=["SAP", "Dias_Ausentismo"])
    sheets = safe_sheet_names(file); sheet = "ausentismos" if "ausentismos" in sheets else sheets[0]
    header = detect_header_row(file, sheet, ["personal", "dias", "ausent"])
    df = read_sheet(file, sheet, header)
    c_sap = find_col(df, ["Número de personal", "Nº pers.", "SAP"], True); c_dias = find_col(df, ["Días Ausentismos Real", "Dias Ausentismos Real", "Días presenc./abs.", "Dias", "Días"], True)
    c_ok = find_col(df, ["correcto?", "correcto"])
    out = pd.DataFrame({"SAP": df[c_sap].map(to_sap), "Dias_Ausentismo": df[c_dias].map(to_number)})
    if c_ok:
        mask = df[c_ok].map(lambda x: yes_no(x, False))
        if mask.sum() > 0: out = out[mask]
    return out[out["SAP"] != ""].groupby("SAP", as_index=False)["Dias_Ausentismo"].sum()

def read_generic_concept_file(file, fuente, periodo_ini, periodo_fin, kind=""):
    if file is None: return pd.DataFrame()
    sheets = safe_sheet_names(file); sheet = next((s for s in ["Novedades","IT 14","IT14","IT 15","IT15","Sheet1"] if s in sheets), sheets[0])
    header = detect_header_row(file, sheet, ["sap", "cc", "valor", "importe", "nº"])
    df = read_sheet(file, sheet, header)
    c_sap = find_col(df, ["SAP", "Nº pers.", "N° pers.", "Número de personal"], True)
    c_con = find_col(df, ["CC-nómina", "CC nomina", "Concepto", "CC"], True)
    c_val = find_col(df, ["Valor", "Importe", "Monto", "Pago", "Total"], True)
    c_txt = find_col(df, ["Texto", "Texto concepto", "CC-nómina_2", "Denominación"])
    c_fecha = find_col(df, ["Fecha", "Fecha pago", "Fecha de pago"]); c_desde = find_col(df, ["Desde", "Fecha desde"]); c_hasta = find_col(df, ["Hasta", "Fecha hasta"]); c_cant = find_col(df, ["Cantidad", "Cant", "Horas"])
    out = pd.DataFrame(); out["SAP"] = df[c_sap].map(to_sap); out["Concepto"] = df[c_con].map(to_concept); out["Valor"] = df[c_val].map(to_number)
    out["Texto_Concepto"] = df[c_txt].fillna("").astype(str).str.strip() if c_txt else ""; out["Cantidad"] = df[c_cant].map(to_number) if c_cant else 0.0
    out["Fecha"] = to_datetime_series(df[c_fecha]) if c_fecha else pd.NaT; out["Desde"] = to_datetime_series(df[c_desde]) if c_desde else pd.NaT; out["Hasta"] = to_datetime_series(df[c_hasta]) if c_hasta else pd.NaT
    out["Fuente"] = fuente; out["Periodo"] = periodo_ini.strftime("%Y-%m")
    out = out[(out["SAP"] != "") & out["Concepto"].str.startswith("Y") & (out["Valor"] != 0)]
    if kind == "IT14":
        out = out[(out["Desde"].isna() | (out["Desde"] <= periodo_fin)) & (out["Hasta"].isna() | (out["Hasta"] >= periodo_ini) | (out["Hasta"].dt.year >= 9999))]
    if kind == "IT15" and out["Fecha"].notna().any():
        out = out[(out["Fecha"] >= periodo_ini) & (out["Fecha"] <= periodo_fin)]
    return out.reset_index(drop=True)

def read_real_retires(file):
    if file is None: return pd.DataFrame(columns=["SAP", "Fecha_Retiro_Real"])
    df = read_sheet(file); c_sap = find_col(df, ["SAP", "Nº pers.", "Número de personal"], True); c_fecha = find_col(df, ["Fecha retiro", "Fecha de retiro", "Baja", "Fecha baja"], True)
    out = pd.DataFrame({"SAP": df[c_sap].map(to_sap), "Fecha_Retiro_Real": to_datetime_series(df[c_fecha])})
    return out[(out["SAP"] != "") & out["Fecha_Retiro_Real"].notna()].drop_duplicates("SAP", keep="last")

def read_projected_retires(file):
    if file is None: return pd.DataFrame()
    df = read_sheet(file); c_cargo = find_col(df, ["Cargo", "Función", "Funcion"], True); c_qty = find_col(df, ["Cantidad", "Cant", "Retiros"], True); c_fecha = find_col(df, ["Fecha retiro", "Fecha de retiro", "Fecha proyectada", "Fecha"], True)
    c_tipo = find_col(df, ["Tipo CECO", "Tipo_CECO", "Negocio", "Ceco"]); c_area = find_col(df, ["Área de nómina", "Area de nomina"])
    out = pd.DataFrame({"Cargo": df[c_cargo].fillna("").astype(str).str.strip(), "Cantidad_Retiros": df[c_qty].map(to_number).astype(int), "Fecha_Retiro_Proyectada": to_datetime_series(df[c_fecha])})
    out["Cargo_Key"] = out["Cargo"].map(norm_key); out["Tipo_CECO"] = df[c_tipo].fillna("").astype(str).str.strip() if c_tipo else ""; out["Area_Nomina"] = df[c_area].fillna("").astype(str).str.strip() if c_area else ""
    return out[(out["Cargo_Key"] != "") & (out["Cantidad_Retiros"] > 0) & out["Fecha_Retiro_Proyectada"].notna()].reset_index(drop=True)

def read_recruitment_raw(file):
    if file is None: return pd.DataFrame()
    sheets = safe_sheet_names(file); sheet = "Proyección de Ingresos" if "Proyección de Ingresos" in sheets else sheets[0]
    df = read_sheet(file, sheet)
    c_fecha = find_col(df, ["Fecha de ingreso", "Fecha ingreso", "Fecha"], True); c_cargo = find_col(df, ["Cargo", "Función", "Funcion"], True)
    c_qty = find_col(df, ["# Posiciones", "Posiciones", "Cantidad", "Vacantes"]); c_ceco = find_col(df, ["Cecos", "Ce.coste", "CECO", "Centro de coste"]); c_area = find_col(df, ["Área de nómina", "Area de nomina"]); c_nivel = find_col(df, ["Nivel", "Gr.prof."])
    df["_fecha"] = to_datetime_series(df[c_fecha]); df["_qty"] = df[c_qty].map(to_number).fillna(1) if c_qty else 1
    rows=[]
    for i,r in df[df["_fecha"].notna()].iterrows():
        qty = min(max(int(r.get("_qty",1)), 0), 300); cargo = str(r.get(c_cargo, "") or "").strip(); ceco = to_ceco(r.get(c_ceco,"")) if c_ceco else ""
        if not ceco: ceco = "1019999999"
        area = str(r.get(c_area, "MENSUAL ADMON 365") or "MENSUAL ADMON 365").strip() if c_area else "MENSUAL ADMON 365"
        for n in range(qty):
            rows.append({"SAP": f"ING-{i+1:04d}-{n+1}", "Nombre": f"Ingreso proyectado - {cargo}", "Area_Nomina": area, "CECO": ceco, "Tipo_CECO": classify_ceco(ceco), "Centro_Coste": "", "Cargo": cargo, "Cargo_Key": norm_key(cargo), "Nivel": str(r.get(c_nivel, "") or "") if c_nivel else "", "Fecha_Ingreso": r["_fecha"], "Fecha_Retiro": pd.NaT, "Tipo_Salario": "Sueldo Básico", "Concepto_Salario_MD": "Y010", "Fuente_Empleado": "Ingreso proyectado"})
    return pd.DataFrame(rows)

# ============================================================
# Transformaciones y cálculos
# ============================================================
def apply_real_retires(md, retires):
    if retires.empty: return md
    out = md.copy(); mp = dict(zip(retires["SAP"], retires["Fecha_Retiro_Real"])); mask = out["SAP"].isin(mp)
    out.loc[mask, "Fecha_Retiro"] = out.loc[mask, "SAP"].map(mp); out.loc[mask, "Fuente_Empleado"] += " + Retiro real"
    return out

def select_projected_retires(md, req, abs_df, seed=2026):
    if req.empty: return md, pd.DataFrame(), pd.DataFrame()
    rng = np.random.default_rng(seed); out = md.copy(); aus = set(abs_df.loc[abs_df["Dias_Ausentismo"] > 0, "SAP"]) if not abs_df.empty else set(); selected=set(); rows=[]; alerts=[]
    for _, r in req.iterrows():
        cand = out[(out["Cargo_Key"] == r["Cargo_Key"]) & out["Fecha_Retiro"].isna()].copy()
        if r.get("Tipo_CECO", ""): cand = cand[cand["Tipo_CECO"].astype(str).str.lower() == str(r["Tipo_CECO"]).lower()]
        if r.get("Area_Nomina", ""): cand = cand[cand["Area_Nomina"].map(norm_key) == norm_key(r["Area_Nomina"])]
        cand = cand[~cand["SAP"].isin(aus) & ~cand["SAP"].isin(selected)].copy()
        cand["Random"] = rng.random(len(cand)) if len(cand) else []
        take = cand.sort_values("Random").head(int(r["Cantidad_Retiros"]))
        if len(take) < int(r["Cantidad_Retiros"]): alerts.append({"Tipo": "Retiros proyectados insuficientes", "Detalle": r["Cargo"], "Valor": f"Solicita {r['Cantidad_Retiros']}, disponibles {len(take)}"})
        for _, t in take.iterrows():
            selected.add(t["SAP"]); out.loc[out["SAP"] == t["SAP"], "Fecha_Retiro"] = r["Fecha_Retiro_Proyectada"]; out.loc[out["SAP"] == t["SAP"], "Fuente_Empleado"] += " + Retiro proyectado"
            rows.append({"SAP": t["SAP"], "Nombre": t["Nombre"], "Cargo": t["Cargo"], "CECO": t["CECO"], "Tipo_CECO": t["Tipo_CECO"], "Fecha_Retiro_Proyectada": r["Fecha_Retiro_Proyectada"], "Cargo_Solicitado": r["Cargo"]})
    return out, pd.DataFrame(rows), pd.DataFrame(alerts)

def assign_recruitment_salary(recl, md, manual_map=None):
    if recl.empty: return recl, pd.DataFrame()
    manual_map = manual_map or {}; md2 = md[(md["Cargo_Key"] != "") & (md["Salario_Total_MD"] > 0)].copy(); md2["Area_Key"] = md2["Area_Nomina"].map(norm_key); md2 = md2.sort_values("Fecha_Ingreso", ascending=False, na_position="last")
    out = recl.copy(); out["Area_Key"] = out["Area_Nomina"].map(norm_key); miss=[]
    for idx, r in out.iterrows():
        checks = [(md2[(md2["Cargo_Key"]==r["Cargo_Key"]) & (md2["Tipo_CECO"]==r["Tipo_CECO"]) & (md2["Area_Key"]==r["Area_Key"])], "Cargo + Tipo CECO + Área"), (md2[(md2["Cargo_Key"]==r["Cargo_Key"]) & (md2["Tipo_CECO"]==r["Tipo_CECO"])], "Cargo + Tipo CECO"), (md2[md2["Cargo_Key"]==r["Cargo_Key"]], "Cargo global")]
        found = None; regla = ""
        for m, rule in checks:
            if not m.empty: found = m.iloc[0]; regla = rule; break
        key = f"{r['Cargo']}||{r['Tipo_CECO']}||{r['Area_Nomina']}"
        if found is not None:
            out.loc[idx, "Salario_Total_MD"] = float(found["Salario_Total_MD"]); out.loc[idx, "SAP_Referencia_Salario"] = found["SAP"]; out.loc[idx, "Regla_Salario_Ingreso"] = regla
        elif float(manual_map.get(key, 0) or 0) > 0:
            out.loc[idx, "Salario_Total_MD"] = float(manual_map[key]); out.loc[idx, "SAP_Referencia_Salario"] = "MANUAL"; out.loc[idx, "Regla_Salario_Ingreso"] = "Manual usuario"
        else:
            out.loc[idx, "Salario_Total_MD"] = 0; out.loc[idx, "Regla_Salario_Ingreso"] = "Pendiente salario"; miss.append({"Cargo": r["Cargo"], "Tipo_CECO": r["Tipo_CECO"], "Area_Nomina": r["Area_Nomina"], "Cantidad_Registros": 1, "Key_Manual": key, "Salario_Manual": 0.0})
    missing = pd.DataFrame(miss)
    if not missing.empty: missing = missing.groupby(["Cargo","Tipo_CECO","Area_Nomina","Key_Manual"], as_index=False).agg(Cantidad_Registros=("Cantidad_Registros","sum"), Salario_Manual=("Salario_Manual","max"))
    return out, missing

def apply_salary_admin(md_dim, md_concepts, ger):
    if ger.empty: return md_dim, md_concepts, pd.DataFrame()
    salary = ger[ger["Concepto"].isin(BASIC_SALARY_CONCEPTS)].drop_duplicates(["SAP","Concepto"], keep="last")
    extras = ger[~ger["Concepto"].isin(BASIC_SALARY_CONCEPTS)].copy(); md=md_dim.copy(); con=md_concepts.copy()
    for _, r in salary.iterrows():
        sap, c, val = r["SAP"], r["Concepto"], float(r["Valor"])
        idx = con[(con["SAP"]==sap) & (con["Concepto"]==c)].index
        if len(idx): con.loc[idx, "Importe_Mensual"] = val
        else: con = pd.concat([con, pd.DataFrame([{"SAP": sap, "Concepto": c, "Texto_Concepto": r.get("Texto_Concepto", "Ajuste salario Gerencia"), "Importe_Mensual": val, "Desde": pd.NaT, "Hasta": pd.NaT}])], ignore_index=True)
        md.loc[md["SAP"]==sap, "Salario_Total_MD"] = val; md.loc[md["SAP"]==sap, "Fuente_Empleado"] += " + Ajuste Gerencia"
    return md, con, extras

def calc_base_concepts(md, concepts, abs_df, periodo_ini, periodo_fin, smmlv, aux):
    aus = dict(zip(abs_df.get("SAP", []), abs_df.get("Dias_Ausentismo", []))); emp = md.copy(); emp["Dias_Ausentismo"] = emp["SAP"].map(aus).fillna(0)
    dias=[]
    for _, r in emp.iterrows():
        d,m = calculate_paid_days(r["Area_Nomina"], r["Fecha_Ingreso"], r["Fecha_Retiro"], periodo_ini, periodo_fin, r["Dias_Ausentismo"]); dias.append((r["SAP"],d,m))
    emp = emp.merge(pd.DataFrame(dias, columns=["SAP","Dias_Pagados","Metodo_Dias"]), on="SAP", how="left")
    parts=[]
    if not concepts.empty:
        b = concepts.merge(emp[["SAP","Nombre","Area_Nomina","CECO","Tipo_CECO","Centro_Coste","Cargo","Nivel","Dias_Ausentismo","Dias_Pagados","Metodo_Dias"]], on="SAP", how="left")
        b["Periodo"] = periodo_ini.strftime("%Y-%m"); b["Fuente"] = "MD actual ajustado - básico"; b["Cantidad"] = 0.0
        is_hour = b["Area_Nomina"].map(norm_text).str.contains("parcial") & b["Area_Nomina"].map(norm_text).str.contains("hora")
        b["Valor"] = b["Importe_Mensual"] / 30 * b["Dias_Pagados"]
        b.loc[is_hour, "Valor"] = b.loc[is_hour, "Importe_Mensual"] / 220 * (b.loc[is_hour, "Dias_Pagados"] * 4)
        parts.append(b[b["Valor"] > 0])
    eligible = emp["Tipo_Salario"].map(norm_text).isin(AUX_ELIGIBLE_DESCRIPTIONS) & (emp["Salario_Total_MD"] <= 2*smmlv) & (emp["Dias_Pagados"] > 0)
    a = emp[eligible].copy()
    if not a.empty:
        a["Periodo"] = periodo_ini.strftime("%Y-%m"); a["Concepto"] = AUX_TRANSPORTE_CONCEPT; a["Texto_Concepto"] = "Auxilio de Transporte Legal"; a["Fuente"] = "MD actual ajustado - aux transporte"; a["Importe_Mensual"] = aux; a["Valor"] = (aux/30*a["Dias_Pagados"]).round(0); a["Cantidad"] = 0.0
        parts.append(a)
    cols=["Periodo","SAP","Nombre","Area_Nomina","CECO","Tipo_CECO","Centro_Coste","Cargo","Nivel","Concepto","Texto_Concepto","Fuente","Importe_Mensual","Dias_Ausentismo","Dias_Pagados","Metodo_Dias","Valor","Cantidad"]
    out = pd.concat(parts, ignore_index=True)[cols] if parts else pd.DataFrame(columns=cols)
    return out, emp

def calc_recruitment(recl, periodo_ini, periodo_fin, smmlv, aux):
    rows=[]
    for _, r in recl.iterrows():
        sal=float(r.get("Salario_Total_MD",0) or 0); d,m = calculate_paid_days(r["Area_Nomina"], r["Fecha_Ingreso"], None, periodo_ini, periodo_fin, 0)
        if sal > 0 and d > 0:
            rows.append({"Periodo": periodo_ini.strftime("%Y-%m"), "SAP": r["SAP"], "Nombre": r["Nombre"], "Area_Nomina": r["Area_Nomina"], "CECO": r["CECO"], "Tipo_CECO": r["Tipo_CECO"], "Centro_Coste": r.get("Centro_Coste",""), "Cargo": r["Cargo"], "Nivel": r.get("Nivel",""), "Concepto":"Y010", "Texto_Concepto":"Sueldo Básico - Ingreso proyectado", "Fuente":"Ingreso reclutamiento", "Importe_Mensual":sal, "Dias_Ausentismo":0, "Dias_Pagados":d, "Metodo_Dias":m, "Valor":round(sal/30*d,0), "Cantidad":0.0})
            if sal <= 2*smmlv:
                rows.append({"Periodo": periodo_ini.strftime("%Y-%m"), "SAP": r["SAP"], "Nombre": r["Nombre"], "Area_Nomina": r["Area_Nomina"], "CECO": r["CECO"], "Tipo_CECO": r["Tipo_CECO"], "Centro_Coste": r.get("Centro_Coste",""), "Cargo": r["Cargo"], "Nivel": r.get("Nivel",""), "Concepto":AUX_TRANSPORTE_CONCEPT, "Texto_Concepto":"Auxilio Transporte - Ingreso proyectado", "Fuente":"Ingreso reclutamiento", "Importe_Mensual":aux, "Dias_Ausentismo":0, "Dias_Pagados":d, "Metodo_Dias":m, "Valor":round(aux/30*d,0), "Cantidad":0.0})
    return pd.DataFrame(rows)

def enrich_extra(df, md, periodo_ini):
    if df.empty: return pd.DataFrame()
    cols_emp=["SAP","Nombre","Area_Nomina","CECO","Tipo_CECO","Centro_Coste","Cargo","Nivel"]
    out = df.merge(md[cols_emp], on="SAP", how="left"); out["Periodo"] = periodo_ini.strftime("%Y-%m"); out["Importe_Mensual"] = out["Valor"]; out["Dias_Ausentismo"] = 0; out["Dias_Pagados"] = 30.0; out["Metodo_Dias"] = "Neto cargado por archivo"
    cols=["Periodo","SAP","Nombre","Area_Nomina","CECO","Tipo_CECO","Centro_Coste","Cargo","Nivel","Concepto","Texto_Concepto","Fuente","Importe_Mensual","Dias_Ausentismo","Dias_Pagados","Metodo_Dias","Valor","Cantidad"]
    for c in cols:
        if c not in out.columns: out[c] = 0 if c in ["Valor","Importe_Mensual","Dias_Ausentismo","Dias_Pagados","Cantidad"] else ""
    return out[cols]

# ============================================================
# Proyección horas
# ============================================================
def cargo_map_from_hours_file(file):
    if file is None: return pd.DataFrame()
    sheets=safe_sheet_names(file); sheet=next((s for s in sheets if norm_key(s)=="cargos"), None)
    if not sheet: return pd.DataFrame()
    df=read_sheet(file, sheet); c_cargo=find_col(df,["Cargo","Función","Funcion","Función_2","Funcion_2"]); c_tipo=find_col(df,["TIPO CARGO","Tipo Cargo","Tipo","Agrupación"])
    if not c_cargo or not c_tipo: return pd.DataFrame()
    out=pd.DataFrame({"Cargo_Key": df[c_cargo].map(norm_key), "TIPO_CARGO": df[c_tipo].fillna("").astype(str).str.strip()})
    return out[(out["Cargo_Key"]!="") & (out["TIPO_CARGO"]!="")].drop_duplicates("Cargo_Key", keep="last")

def add_tipo_cargo(df, mapping):
    out=df.copy(); out["Cargo_Key"] = out["Cargo"].map(norm_key) if "Cargo" in out.columns else ""
    if not mapping.empty: out = out.merge(mapping, on="Cargo_Key", how="left")
    else: out["TIPO_CARGO"] = ""
    out["TIPO_CARGO"] = out["TIPO_CARGO"].fillna(""); out.loc[out["TIPO_CARGO"]=="", "TIPO_CARGO"] = out.loc[out["TIPO_CARGO"]=="", "Cargo"].fillna("").astype(str)
    return out

def read_hours_history(file):
    if file is None: return pd.DataFrame()
    sheets=safe_sheet_names(file); sheet=next((s for s in ["Horas_Proyecciones","Horas Proyecciones","Horas","Historico","Histórico"] if s in sheets), sheets[0])
    df=read_sheet(file, sheet); c_con=find_col(df,["CC-n.","CC-nómina","CC nomina","Concepto","CC-n"]); c_qty=find_col(df,["Cantidad","Horas","Cantidad horas","CANT"]); c_period=find_col(df,["Periodo","Mes","Fecha","Source.Name","Archivo"]); c_tipo=find_col(df,["TIPO CARGO","Tipo Cargo","Cargo","Función","Funcion"])
    if not c_con or not c_qty or not c_tipo: return pd.DataFrame()
    out=pd.DataFrame({"Concepto": df[c_con].map(to_concept), "Cantidad_Horas": df[c_qty].map(to_number), "TIPO_CARGO": df[c_tipo].fillna("").astype(str).str.strip()})
    out["Periodo_Fecha"] = to_datetime_series(df[c_period]) if c_period else pd.NaT; out["Periodo_Raw"] = df[c_period].fillna("").astype(str) if c_period else "SIN_PERIODO"; out["Periodo_ID"] = out["Periodo_Fecha"].dt.strftime("%Y-%m"); out.loc[out["Periodo_ID"].isna(), "Periodo_ID"] = out.loc[out["Periodo_ID"].isna(), "Periodo_Raw"]
    return out[out["Concepto"].isin(HOUR_CONCEPTS) & (out["Cantidad_Horas"]!=0) & (out["TIPO_CARGO"]!="")]

def read_hc_history(file):
    if file is None: return pd.DataFrame()
    sheets=safe_sheet_names(file); sheet=next((s for s in sheets if norm_key(s) in ["hc","resumenhcydias"]), None)
    if not sheet: return pd.DataFrame()
    df=read_sheet(file, sheet); c_tipo=find_col(df,["TIPO CARGO","Tipo Cargo","Cargo"]); c_hc=find_col(df,["HC","Headcount","Head count","Cantidad"]); c_period=find_col(df,["Periodo","Mes","Fecha"])
    if not c_tipo or not c_hc: return pd.DataFrame()
    out=pd.DataFrame({"TIPO_CARGO": df[c_tipo].fillna("").astype(str).str.strip(), "HC_Historico": df[c_hc].map(to_number)})
    out["Periodo_Fecha"] = to_datetime_series(df[c_period]) if c_period else pd.NaT; out["Periodo_Raw"] = df[c_period].fillna("").astype(str) if c_period else "SIN_PERIODO"; out["Periodo_ID"] = out["Periodo_Fecha"].dt.strftime("%Y-%m"); out.loc[out["Periodo_ID"].isna(), "Periodo_ID"] = out.loc[out["Periodo_ID"].isna(), "Periodo_Raw"]
    return out[(out["TIPO_CARGO"]!="") & (out["HC_Historico"]>0)]

def project_hours(file, md, recl, year, month, weights_text):
    if file is None: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    mapping=cargo_map_from_hours_file(file); hist=read_hours_history(file); hc_hist=read_hc_history(file); alerts=[]
    if hist.empty: return pd.DataFrame(), mapping, pd.DataFrame([{"Tipo":"Proyección horas","Detalle":"No se encontró histórico de horas", "Valor":None}])
    if hc_hist.empty: alerts.append({"Tipo":"Proyección horas","Detalle":"No se encontró HC histórico. Se usa HC=1 para promedio.", "Valor":None})
    h=hist.groupby(["Periodo_ID","TIPO_CARGO","Concepto"], as_index=False)["Cantidad_Horas"].sum()
    h=h.merge(hc_hist[["Periodo_ID","TIPO_CARGO","HC_Historico"]], on=["Periodo_ID","TIPO_CARGO"], how="left") if not hc_hist.empty else h.assign(HC_Historico=1.0)
    h["HC_Historico"] = h["HC_Historico"].replace(0,np.nan).fillna(1.0)
    def hist_days(row):
        m=re.match(r"^(\d{4})-(\d{2})$", str(row["Periodo_ID"])); dt=HOUR_DAY_TYPE.get(row["Concepto"],"HABILES")
        return count_days_for_hours(int(m.group(1)), int(m.group(2)), dt) if m else (30 if dt=="HABILES" else 5)
    h["Dias_Historicos"]=h.apply(hist_days, axis=1).replace(0,1); h["Prom_Diario_Persona"] = h["Cantidad_Horas"] / h["HC_Historico"] / h["Dias_Historicos"]
    h["Sort"] = h["Periodo_ID"].map(lambda p: int(p[:4])*100+int(p[5:7]) if re.match(r"^\d{4}-\d{2}$", str(p)) else -1); h=h.sort_values("Sort", ascending=False)
    weights=[float(x.replace("%", ""))/100 if float(x.replace("%", ""))>1 else float(x.replace("%", "")) for x in re.split(r"[,;\s]+", weights_text.strip()) if x]
    if not weights: weights=[.4,.3,.2,.1]
    prom=[]
    for (tc, con), g in h.groupby(["TIPO_CARGO","Concepto"]):
        g=g.head(len(weights)); w=np.array(weights[:len(g)], dtype=float); w=w/w.sum()
        prom.append({"TIPO_CARGO":tc,"Concepto":con,"Promedio_Diario_Persona":float((g["Prom_Diario_Persona"].values*w).sum()),"Periodos_Usados":", ".join(g["Periodo_ID"].astype(str)),"Pesos_Usados":", ".join([f"{x:.0%}" for x in w])})
    prom=pd.DataFrame(prom)
    hc=add_tipo_cargo(md, mapping).groupby(["TIPO_CARGO","Tipo_CECO"], as_index=False).agg(HC_Proyectado=("SAP","nunique"))
    if not recl.empty:
        hc_rec=add_tipo_cargo(recl, mapping).groupby(["TIPO_CARGO","Tipo_CECO"], as_index=False).agg(HC_Proyectado=("SAP","nunique")); hc=pd.concat([hc,hc_rec]).groupby(["TIPO_CARGO","Tipo_CECO"], as_index=False)["HC_Proyectado"].sum()
    out=prom.merge(hc, on="TIPO_CARGO", how="left"); out["HC_Proyectado"]=out["HC_Proyectado"].fillna(0); out["Tipo_Dia"]=out["Concepto"].map(lambda c: HOUR_DAY_TYPE.get(c,"HABILES")); out["Dias_Aplicables_Mes_Siguiente"]=out["Tipo_Dia"].map(lambda dt: count_days_for_hours(year, month, dt)); out["Horas_Persona_Mes_Siguiente"]=out["Promedio_Diario_Persona"]*out["Dias_Aplicables_Mes_Siguiente"]; out["Horas_Totales_Proyectadas"]=out["Horas_Persona_Mes_Siguiente"]*out["HC_Proyectado"]
    out["Periodo_Proyectado"]=f"{year}-{month:02d}"; out["CC-n."]=out["Concepto"]; out["Texto a tomar en días"]=out["Tipo_Dia"].map({"HABILES":"Días hábiles","DOM_FEST":"Domingos / festivos"}); out["Llave"]=out["TIPO_CARGO"].astype(str)+out["Concepto"].astype(str)
    cols=["Periodo_Proyectado","Llave","CC-n.","Texto a tomar en días","TIPO_CARGO","Tipo_CECO","Promedio_Diario_Persona","Dias_Aplicables_Mes_Siguiente","Horas_Persona_Mes_Siguiente","HC_Proyectado","Horas_Totales_Proyectadas","Periodos_Usados","Pesos_Usados"]
    return out[cols], mapping, pd.DataFrame(alerts)

# ============================================================
# Homologación / salidas
# ============================================================
def homologate(base, dkon):
    if base.empty: return pd.DataFrame(), pd.DataFrame()
    out=base.merge(dkon, on=["Concepto","Tipo_CECO"], how="left"); missing=out[out["Cuenta_DKON"].isna() | (out["Cuenta_DKON"].astype(str).str.strip()=="")]
    ok=out.drop(missing.index)
    gcols=["Periodo","SAP","Nombre","Area_Nomina","CECO","Tipo_CECO","Centro_Coste","Cargo","Nivel","Cuenta_DKON","Texto_Cuenta","Grupo_DKON","Descripcion_DKON","Fuente","Base_IBC","Base_Prima","Base_Cesantias","Base_Vacaciones","Base_Exoneracion"]
    if ok.empty: return ok, missing
    agg=ok.groupby(gcols, dropna=False).agg(Valor=("Valor","sum"), Conceptos_Agrupados=("Concepto", lambda s: ", ".join(sorted(set(s.astype(str))))), Dias_Pagados_Prom=("Dias_Pagados","mean")).reset_index(); agg["Valor"]=agg["Valor"].round(0)
    return agg, missing

def build_ibc(base, smmlv):
    if base.empty: return pd.DataFrame()
    ibc_src=base[base["Base_IBC"].fillna(False)].copy()
    if ibc_src.empty: return pd.DataFrame()
    ibc=ibc_src.groupby(["Periodo","SAP","Nombre","CECO","Tipo_CECO","Cargo","Area_Nomina"], as_index=False).agg(IBC_Preliminar=("Valor","sum"), Conceptos_IBC=("Concepto", lambda s: ", ".join(sorted(set(s.astype(str))))))
    exo=base[base["Base_Exoneracion"].fillna(False)].groupby("SAP")["Valor"].sum()
    ibc["Devengo_Para_Exoneracion"] = ibc["SAP"].map(exo).fillna(0); ibc["Menor_10_SMMLV"] = ibc["Devengo_Para_Exoneracion"] < 10*smmlv
    ibc["Nota"] = "Base preliminar. Exoneración requiere excluir aprendices/practicantes y validar regla interna."
    return ibc

def build_alerts(md, base, missing, extras):
    rows=[]
    for _, r in md[md["Tipo_CECO"]=="Sin clasificar"].iterrows(): rows.append({"Tipo":"CECO sin clasificar","SAP":r["SAP"],"Detalle":r["CECO"],"Valor":None})
    if not base.empty:
        for _, r in base[base["Regla_Calculo"]=="SIN_REGLA"].iterrows(): rows.append({"Tipo":"Concepto sin regla","SAP":r["SAP"],"Detalle":r["Concepto"],"Valor":r["Valor"]})
    if not missing.empty:
        for _, r in missing.iterrows(): rows.append({"Tipo":"Concepto sin cuenta DKON","SAP":r.get("SAP"),"Detalle":f"{r.get('Concepto')} / {r.get('Tipo_CECO')}","Valor":r.get("Valor")})
    frames=[pd.DataFrame(rows)] + [e for e in extras if e is not None and not e.empty]
    return pd.concat(frames, ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame(columns=["Tipo","SAP","Detalle","Valor"])

def build_excel(dfs: Dict[str, pd.DataFrame]) -> bytes:
    output=io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb=writer.book; header=wb.add_format({"bold":True,"bg_color":"#F59E0B","font_color":"#FFFFFF","border":1}); money=wb.add_format({"num_format":"#,##0"}); num=wb.add_format({"num_format":"#,##0.00"})
        for name, df in dfs.items():
            name=name[:31]; export = df.copy() if df is not None and not df.empty else pd.DataFrame({"Mensaje":["Sin registros"]})
            for c in export.columns:
                if pd.api.types.is_datetime64_any_dtype(export[c]): export[c]=export[c].dt.strftime("%d/%m/%Y")
            export.to_excel(writer, sheet_name=name, index=False); ws=writer.sheets[name]; ws.freeze_panes(1,0)
            for i,c in enumerate(export.columns):
                ws.write(0,i,c,header); nc=norm_col(c); fmt=money if any(x in nc for x in ["valor","importe","salario","ibc","devengo"]) else (num if any(x in nc for x in ["horas","promedio","dias"]) else None)
                width=min(max([len(str(c))]+[len(str(v)) for v in export[c].head(100).fillna("").tolist()])+2,45); ws.set_column(i,i,width,fmt)
    output.seek(0); return output.getvalue()

# ============================================================
# UI
# ============================================================
st.set_page_config(page_title=APP_TITLE, page_icon="💼", layout="wide")
st.markdown("""
<style>
.main {background: linear-gradient(180deg, #fff7ed 0%, #ffffff 30%);} .block-container {padding-top: 1.2rem;}
.big-title {font-size: 2.1rem; font-weight: 800; color: #7c2d12;} .subtitle {font-size: 1rem; color: #57534e; margin-bottom: 1.3rem;}
div[data-testid="stMetric"] {background:#fff7ed; border:1px solid #fed7aa; padding:12px; border-radius:14px;}
.footer {font-size:.82rem; color:#78716c; margin-top:2rem;}
</style>""", unsafe_allow_html=True)
st.markdown('<div class="big-title">💼 Modelo proyecciones de nómina JMC</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">V5 · Base detalle por concepto, novedades, retiros, IT14/IT15, horas pagas y proyección de horas del mes siguiente.</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Parámetros")
    periodo_ini=pd.Timestamp(st.date_input("Fecha inicio del periodo de cálculo", value=date(2026,5,1)))
    periodo_fin=pd.Timestamp(st.date_input("Fecha fin del periodo de cálculo", value=date(2026,5,31)))
    target_date=st.date_input("Mes a proyectar horas", value=date(2026,6,1))
    pesos_horas=st.text_input("Pesos promedio ponderado horas", value="40,30,20,10")
    smmlv=st.number_input("SMMLV", min_value=0, value=DEFAULT_SMMLV, step=1000, format="%d")
    aux=st.number_input("Auxilio transporte legal", min_value=0, value=DEFAULT_AUX_TRANSPORTE, step=1000, format="%d")
    seed=st.number_input("Semilla retiros proyectados", min_value=1, value=2026, step=1)

st.subheader("1. Archivos principales")
c1,c2,c3=st.columns(3)
with c1: dkon_file=st.file_uploader("DKON", type=["xlsx","xlsm","xls"])
with c2: md_ant_file=st.file_uploader("MD mes anterior", type=["xlsx","xlsm","xls"])
with c3: md_act_file=st.file_uploader("MD mes actual", type=["xlsx","xlsm","xls"])

st.subheader("2. Novedades")
c4,c5,c6=st.columns(3)
with c4: ger_file=st.file_uploader("Novedades Gerencia Administrativa", type=["xlsx","xlsm","xls"])
with c5: cb_file=st.file_uploader("Compensación y Beneficios", type=["xlsx","xlsm","xls"])
with c6: rules_file=st.file_uploader("Reglas de conceptos (opcional)", type=["xlsx","xlsm","xls"])

c7,c8,c9=st.columns(3)
with c7: it14_file=st.file_uploader("IT14", type=["xlsx","xlsm","xls"])
with c8: it15_file=st.file_uploader("IT15", type=["xlsx","xlsm","xls"])
with c9: horas_pagas_file=st.file_uploader("Horas pagas del mes", type=["xlsx","xlsm","xls"])

st.subheader("3. Planta y días")
c10,c11,c12,c13=st.columns(4)
with c10: recl_file=st.file_uploader("Ingresos reclutamiento", type=["xlsx","xlsm","xls"])
with c11: abs_file=st.file_uploader("Proyección ausentismos", type=["xlsx","xlsm","xls"])
with c12: ret_real_file=st.file_uploader("Retiros reales / masterdata retiros", type=["xlsx","xlsm","xls"])
with c13: ret_proy_file=st.file_uploader("Retiros proyectados por cargo", type=["xlsx","xlsm","xls"])

st.subheader("4. Proyección de horas del mes siguiente")
hours_model_file=st.file_uploader("Archivo histórico/promedios ponderados de horas", type=["xlsx","xlsm","xls"])
st.info("La hoja `LLEVAR_A_CALCULO` calcula cantidad de horas del mes siguiente. No entra a IBC ni prestaciones; sirve para el insumo financiero posterior.")

if st.button("🚀 Generar base V5", type="primary"):
    if not dkon_file or not md_act_file:
        st.error("Carga mínimo DKON y MD mes actual."); st.stop()
    try:
        dkon=build_dkon_matrix(dkon_file); rules=read_rules(rules_file, dkon)
        md=read_md_dimension(md_act_file); md_con=read_md_active_concepts(md_act_file)
        abs_df=read_absences(abs_file) if abs_file else pd.DataFrame(columns=["SAP","Dias_Ausentismo"])
        ret_real=read_real_retires(ret_real_file) if ret_real_file else pd.DataFrame(columns=["SAP","Fecha_Retiro_Real"])
        ret_proy=read_projected_retires(ret_proy_file) if ret_proy_file else pd.DataFrame()
        md=apply_real_retires(md, ret_real); md, ret_sel, alert_ret=select_projected_retires(md, ret_proy, abs_df, int(seed))
        ger=read_generic_concept_file(ger_file,"Gerencia Administrativa",periodo_ini,periodo_fin) if ger_file else pd.DataFrame()
        cb=read_generic_concept_file(cb_file,"Compensación y Beneficios",periodo_ini,periodo_fin) if cb_file else pd.DataFrame()
        it14=read_generic_concept_file(it14_file,"IT14",periodo_ini,periodo_fin,"IT14") if it14_file else pd.DataFrame()
        it15=read_generic_concept_file(it15_file,"IT15",periodo_ini,periodo_fin,"IT15") if it15_file else pd.DataFrame()
        hp=read_generic_concept_file(horas_pagas_file,"Horas pagas del mes",periodo_ini,periodo_fin) if horas_pagas_file else pd.DataFrame()
        md, md_con, ger_extra=apply_salary_admin(md, md_con, ger)
        recl_raw=read_recruitment_raw(recl_file) if recl_file else pd.DataFrame(); recl, missing=assign_recruitment_salary(recl_raw, md)
        if not missing.empty:
            st.warning("Hay cargos de ingresos que no existen en MD. Completa salario manual.")
            edited=st.data_editor(missing, use_container_width=True, key="salary_editor")
            manual=dict(zip(edited["Key_Manual"], edited["Salario_Manual"].map(to_number)))
            recl, missing2=assign_recruitment_salary(recl_raw, md, manual)
            if not missing2.empty:
                st.error("Aún hay cargos sin salario manual."); st.stop()
        base_md, md_days=calc_base_concepts(md, md_con, abs_df, periodo_ini, periodo_fin, smmlv, aux)
        base_ing=calc_recruitment(recl, periodo_ini, periodo_fin, smmlv, aux) if not recl.empty else pd.DataFrame()
        extras=[enrich_extra(x, md, periodo_ini) for x in [ger_extra, cb, it14, it15, hp] if x is not None and not x.empty]
        base_extra=pd.concat(extras, ignore_index=True) if extras else pd.DataFrame()
        parts=[x for x in [base_md, base_ing, base_extra] if x is not None and not x.empty]
        base=pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(); base=add_rule_flags(base, rules)
        cuentas, missing_dkon=homologate(base, dkon); ibc=build_ibc(base, smmlv)
        resumen_cuenta=cuentas.groupby(["Tipo_CECO","Cuenta_DKON","Texto_Cuenta","Grupo_DKON"], as_index=False)["Valor"].sum() if not cuentas.empty else pd.DataFrame()
        resumen_ceco=cuentas.groupby(["Tipo_CECO","CECO","Centro_Coste","Cuenta_DKON","Texto_Cuenta"], as_index=False)["Valor"].sum() if not cuentas.empty else pd.DataFrame()
        resumen_fuente=base.groupby(["Fuente","Concepto"], as_index=False)["Valor"].sum() if not base.empty else pd.DataFrame()
        comp_md=pd.DataFrame()
        if md_ant_file:
            md_ant=read_md_dimension(md_ant_file)
            ant=md_ant[["SAP","Nombre","CECO","Tipo_CECO","Salario_Total_MD","Cargo"]].rename(columns={"Nombre":"Nombre_Ant","CECO":"CECO_Ant","Tipo_CECO":"Tipo_CECO_Ant","Salario_Total_MD":"Salario_Ant","Cargo":"Cargo_Ant"})
            act=md[["SAP","Nombre","CECO","Tipo_CECO","Salario_Total_MD","Cargo"]].rename(columns={"Nombre":"Nombre_Act","CECO":"CECO_Act","Tipo_CECO":"Tipo_CECO_Act","Salario_Total_MD":"Salario_Act","Cargo":"Cargo_Act"})
            comp_md=ant.merge(act,on="SAP",how="outer"); comp_md["Estado"]=comp_md.apply(lambda r: "Nuevo" if pd.isna(r["CECO_Ant"]) else ("Salida" if pd.isna(r["CECO_Act"]) else "Continúa"), axis=1); comp_md["Dif_Salario"]=comp_md["Salario_Act"].fillna(0)-comp_md["Salario_Ant"].fillna(0)
        llevar, mapa_cargos, alert_horas=project_hours(hours_model_file, md, recl, target_date.year, target_date.month, pesos_horas) if hours_model_file else (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        alertas=build_alerts(md, base, missing_dkon, [alert_ret, alert_horas])
        st.success("Base V5 generada correctamente.")
        m1,m2,m3,m4,m5,m6=st.columns(6); m1.metric("Conceptos DKON", f"{dkon['Concepto'].nunique():,}"); m2.metric("HC MD", f"{md['SAP'].nunique():,}"); m3.metric("Detalle", f"{len(base):,}"); m4.metric("Ingresos", f"{len(recl):,}" if not recl.empty else "0"); m5.metric("Retiros proy.", f"{len(ret_sel):,}" if not ret_sel.empty else "0"); m6.metric("Alertas", f"{len(alertas):,}")
        tabs=st.tabs(["Detalle", "Cuentas", "Resumen cuenta", "IBC preliminar", "LLEVAR_A_CALCULO", "Alertas"])
        with tabs[0]: st.dataframe(base.head(200), use_container_width=True)
        with tabs[1]: st.dataframe(cuentas.head(200), use_container_width=True)
        with tabs[2]: st.dataframe(resumen_cuenta, use_container_width=True)
        with tabs[3]: st.dataframe(ibc, use_container_width=True)
        with tabs[4]: st.dataframe(llevar, use_container_width=True)
        with tabs[5]: st.dataframe(alertas, use_container_width=True)
        dfs={"MATRIZ_DKON_Y":dkon,"REGLAS_CONCEPTOS":rules,"MD_NORMALIZADO":md,"MD_DIAS_CALCULADOS":md_days,"AUSENTISMOS_RESUMEN":abs_df,"RETIROS_REALES":ret_real,"RETIROS_PROYECTADOS":ret_proy,"RETIROS_SELECCIONADOS":ret_sel,"INGRESOS_PROYECTADOS":recl,"NOVEDADES_GERENCIA":ger,"COMP_BENEFICIOS":cb,"IT14_FILTRADO":it14,"IT15_FILTRADO":it15,"HORAS_PAGAS_MES":hp,"BASE_DETALLE_CONCEPTO":base,"BASE_CUENTAS_DKON":cuentas,"BASE_IBC_PRELIMINAR":ibc,"LLEVAR_A_CALCULO":llevar,"MAPA_CARGOS_HORAS":mapa_cargos,"RESUMEN_CUENTA":resumen_cuenta,"RESUMEN_CECO":resumen_ceco,"RESUMEN_FUENTE":resumen_fuente,"COMPARATIVO_MD":comp_md,"ALERTAS":alertas}
        st.download_button("📥 Descargar base Excel V5", data=build_excel(dfs), file_name=f"base_proyeccion_costos_v5_{periodo_ini.strftime('%Y_%m')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    except Exception as e:
        st.exception(e); st.error("Se presentó un error. Revisa hojas y columnas esperadas.")

st.markdown('<div class="footer">Creado por Andrés Huérfano Dávila – Nómina JMC</div>', unsafe_allow_html=True)
