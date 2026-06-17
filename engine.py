import io
import re
import unicodedata
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

APP_TITLE = "Modelo Integral Proyecciones Nómina JMC"
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
def _find_optional_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    return find_col(df, candidates, required=False)

def _bool_from_col(df: pd.DataFrame, col: Optional[str], default=False) -> pd.Series:
    if col and col in df.columns:
        return df[col].map(lambda x: yes_no(x, default))
    return pd.Series([default] * len(df), index=df.index)

def build_dkon_matrix(file) -> pd.DataFrame:
    """Construye matriz DKON enriquecida.

    Llave central:
        Concepto Y + Tipo_CECO = Cuenta DKON + marcas laborales/financieras.

    El DKON puede venir con columnas nuevas:
      - Salarial / Seguridad Social
      - LEY 1393
      - Base parafiscales
      - Base Vacaciones
      - Base prestaciones sociales

    Si alguna columna no existe, la app deja una marca de origen y usa defaults conservadores
    para que el MVP siga funcionando, pero queda alerta para completar DKON.
    """
    sheets = safe_sheet_names(file)
    sheet = "Sheet1" if "Sheet1" in sheets else sheets[0]
    df = read_sheet(file, sheet)

    c_con = find_col(df, ["CC-nómina", "CC nomina", "CC-nomina"], True)
    c_txt = find_col(df, ["Txt.CC-nóm.", "Texto CC nomina", "Texto concepto"])
    c_acc = find_col(df, ["Cta.mayor", "Cta mayor", "Cuenta mayor"], True)
    c_acc_txt = find_col(df, ["Texto breve", "Texto cuenta"])
    c_group = find_col(df, ["CUENTA", "Grupo", "Grupo de cuentas"])
    c_desc = find_col(df, ["Descripcion ", "Descripción", "Descripcion"])

    c_ss = _find_optional_col(df, ["Salarial / Seguridad Social", "Salarial Seguridad Social", "Seguridad Social", "Base IBC", "Base SS", "IBC", "Salarial"])
    c_ley1393 = _find_optional_col(df, ["LEY 1393", "Ley 1393", "1393"])
    c_paraf = _find_optional_col(df, ["Base parafiscales", "Base Parafiscales", "Parafiscales"])
    c_vac = _find_optional_col(df, ["Base Vacaciones", "Vacaciones"])
    c_prest = _find_optional_col(df, ["Base prestaciones sociales", "Base Prestaciones Sociales", "Prestaciones sociales", "Base prestaciones", "Prestaciones"])
    c_regla = _find_optional_col(df, ["Regla cálculo", "Regla_Calculo", "Regla Calculo", "Regla"])

    out = pd.DataFrame(index=df.index)
    out["Concepto"] = df[c_con].map(to_concept)
    out["Cuenta_DKON"] = df[c_acc].map(to_ceco)
    out = out[out["Concepto"].str.startswith("Y", na=False) & out["Cuenta_DKON"].str[:2].isin(["60", "62", "63"])].copy()
    out["Tipo_CECO"] = out["Cuenta_DKON"].str[:2].map(TIPO_CECO_BY_ACCOUNT_PREFIX)

    out["Texto_Concepto_DKON"] = df.loc[out.index, c_txt].fillna("").astype(str).str.strip() if c_txt else ""
    out["Texto_Cuenta"] = df.loc[out.index, c_acc_txt].fillna("").astype(str).str.strip() if c_acc_txt else ""
    out["Grupo_DKON"] = df.loc[out.index, c_group].fillna("").astype(str).str.strip() if c_group else ""
    out["Descripcion_DKON"] = df.loc[out.index, c_desc].fillna("").astype(str).str.strip() if c_desc else ""

    # Defaults fallback si el DKON todavía no tiene las columnas enriquecidas.
    # Cuando el DKON trae columnas, se obedece el archivo.
    def default_base(concepto, flag):
        if concepto in BASIC_SALARY_CONCEPTS:
            return True
        if concepto == AUX_TRANSPORTE_CONCEPT:
            return flag in ["paraf", "prest", "exo"]  # aux no IBC ni vacaciones por defecto
        if concepto in HOUR_CONCEPTS:
            return flag in ["ibc", "paraf", "prest", "exo"]
        return flag == "exo"

    if c_ss:
        out["Salarial_Seguridad_Social"] = df.loc[out.index, c_ss].map(lambda x: yes_no(x, False))
        out["Base_IBC"] = out["Salarial_Seguridad_Social"]
    else:
        out["Base_IBC"] = out["Concepto"].map(lambda c: default_base(c, "ibc"))
        out["Salarial_Seguridad_Social"] = out["Base_IBC"]

    out["LEY_1393"] = df.loc[out.index, c_ley1393].fillna("").astype(str).str.strip() if c_ley1393 else ""
    out["Base_Parafiscales"] = df.loc[out.index, c_paraf].map(lambda x: yes_no(x, False)) if c_paraf else out["Concepto"].map(lambda c: default_base(c, "paraf"))
    out["Base_Vacaciones"] = df.loc[out.index, c_vac].map(lambda x: yes_no(x, False)) if c_vac else out["Concepto"].map(lambda c: default_base(c, "vac"))
    out["Base_Prestaciones"] = df.loc[out.index, c_prest].map(lambda x: yes_no(x, False)) if c_prest else out["Concepto"].map(lambda c: default_base(c, "prest"))
    out["Base_Exoneracion"] = out["Concepto"].map(lambda c: default_base(c, "exo"))

    if c_regla:
        out["Regla_Calculo"] = df.loc[out.index, c_regla].fillna("NETO").astype(str).str.upper().str.strip()
    else:
        out["Regla_Calculo"] = out["Concepto"].map(lambda c: "PROPORCIONAL_DIAS" if c in BASIC_SALARY_CONCEPTS or c == AUX_TRANSPORTE_CONCEPT else "NETO")

    out["Origen_Marcacion_DKON"] = "DKON enriquecido" if any([c_ss, c_paraf, c_vac, c_prest]) else "Default MVP - completar DKON"

    cols = [
        "Concepto", "Texto_Concepto_DKON", "Tipo_CECO", "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON",
        "Salarial_Seguridad_Social", "LEY_1393", "Base_IBC", "Base_Parafiscales", "Base_Vacaciones", "Base_Prestaciones",
        "Base_Exoneracion", "Regla_Calculo", "Origen_Marcacion_DKON",
    ]
    out = out[cols].drop_duplicates().sort_values(["Concepto", "Tipo_CECO", "Cuenta_DKON"])
    return out.drop_duplicates(["Concepto", "Tipo_CECO"], keep="first").reset_index(drop=True)

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

def read_projected_retires(file, default_fecha=None):
    """Lee la solicitud de retiros proyectados por cargo.

    Estructura ideal:
      Cargo | Cantidad | Fecha retiro proyectada | Tipo CECO | Área de nómina

    Pero el archivo que hoy usan en el query puede traer solo Cargo + Cantidad.
    En ese caso no se rompe la app: usa default_fecha, normalmente la fecha fin del periodo.
    """
    if file is None:
        return pd.DataFrame()

    sheets = safe_sheet_names(file)
    # Si existe TablaResumen, suele ser la tabla limpia del archivo de retiros por cargo.
    sheet = "TablaResumen" if "TablaResumen" in sheets else ("Hoja2" if "Hoja2" in sheets else sheets[0])

    # Intento normal. Si la primera fila no es encabezado útil, detectamos.
    df = read_sheet(file, sheet)
    if not find_col(df, ["Cargo", "Función", "Funcion"], False) or not find_col(df, ["Cantidad", "Cant", "Retiros", "Cuenta de cargo"], False):
        header = detect_header_row(file, sheet, ["cargo", "cantidad", "retiros"], max_rows=12)
        df = read_sheet(file, sheet, header)

    c_cargo = find_col(df, ["Cargo", "Función", "Funcion", "cargo_normalizado"], True)
    c_qty = find_col(df, ["Cantidad retiros", "Cantidad_Retiros", "Cantidad", "Cant", "Retiros", "Cuenta de cargo", "Cuenta"], True)
    c_fecha = find_col(df, [
        "Fecha retiro proyectada", "Fecha_Retiro_Proyectada", "Fecha retiro", "Fecha de retiro",
        "Fecha proyectada", "Fecha baja", "Baja", "Fec retiro", "Fecha"
    ], False)
    c_tipo = find_col(df, ["Tipo CECO", "Tipo_CECO", "Negocio", "Ceco", "Tipo", "Área"], False)
    c_area = find_col(df, ["Área de nómina", "Area de nomina", "Area_Nomina"], False)

    out = pd.DataFrame()
    out["Cargo"] = df[c_cargo].fillna("").astype(str).str.strip()
    out["Cantidad_Retiros"] = df[c_qty].map(to_number).fillna(0).astype(int)

    if c_fecha:
        out["Fecha_Retiro_Proyectada"] = to_datetime_series(df[c_fecha])
        out["Fecha_Retiro_Origen"] = "Archivo"
    else:
        fecha_default = pd.Timestamp(default_fecha).normalize() if default_fecha is not None else pd.NaT
        out["Fecha_Retiro_Proyectada"] = fecha_default
        out["Fecha_Retiro_Origen"] = "Default fin periodo" if pd.notna(fecha_default) else "Pendiente fecha"

    out["Cargo_Key"] = out["Cargo"].map(norm_key)
    out["Tipo_CECO"] = df[c_tipo].fillna("").astype(str).str.strip() if c_tipo else ""
    out["Area_Nomina"] = df[c_area].fillna("").astype(str).str.strip() if c_area else ""

    out = out[(out["Cargo_Key"] != "") & (out["Cantidad_Retiros"] > 0)].copy()
    return out.reset_index(drop=True)

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
# Salidas V5.2 desde DKON enriquecido
# ============================================================
def attach_dkon_attributes(base: pd.DataFrame, dkon: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if base.empty:
        return base, pd.DataFrame()
    attrs = [
        "Concepto", "Tipo_CECO", "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON",
        "Texto_Concepto_DKON", "Salarial_Seguridad_Social", "LEY_1393", "Base_IBC", "Base_Parafiscales",
        "Base_Vacaciones", "Base_Prestaciones", "Base_Exoneracion", "Regla_Calculo", "Origen_Marcacion_DKON",
    ]
    out = base.merge(dkon[attrs], on=["Concepto", "Tipo_CECO"], how="left")
    for c in ["Salarial_Seguridad_Social", "Base_IBC", "Base_Parafiscales", "Base_Vacaciones", "Base_Prestaciones", "Base_Exoneracion"]:
        out[c] = out[c].fillna(False).astype(bool)
    out["Regla_Calculo"] = out["Regla_Calculo"].fillna("SIN_DKON")
    out["Origen_Marcacion_DKON"] = out["Origen_Marcacion_DKON"].fillna("Sin DKON")
    missing = out[out["Cuenta_DKON"].isna() | (out["Cuenta_DKON"].astype(str).str.strip() == "")].copy()
    return out, missing

def homologate(base: pd.DataFrame, dkon: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if base.empty:
        return pd.DataFrame(), pd.DataFrame()
    if "Cuenta_DKON" not in base.columns:
        base, missing = attach_dkon_attributes(base, dkon)
    else:
        missing = base[base["Cuenta_DKON"].isna() | (base["Cuenta_DKON"].astype(str).str.strip() == "")].copy()
    ok = base.drop(missing.index, errors="ignore").copy()
    if ok.empty:
        return ok, missing
    gcols = [
        "Periodo", "SAP", "Nombre", "Area_Nomina", "CECO", "Tipo_CECO", "Centro_Coste", "Cargo", "Nivel",
        "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Descripcion_DKON", "Fuente",
        "Salarial_Seguridad_Social", "LEY_1393", "Base_IBC", "Base_Parafiscales", "Base_Vacaciones", "Base_Prestaciones", "Base_Exoneracion",
    ]
    for c in gcols:
        if c not in ok.columns:
            ok[c] = "" if c not in ["Base_IBC", "Base_Parafiscales", "Base_Vacaciones", "Base_Prestaciones", "Base_Exoneracion", "Salarial_Seguridad_Social"] else False
    agg = ok.groupby(gcols, dropna=False).agg(
        Valor=("Valor", "sum"),
        Conceptos_Agrupados=("Concepto", lambda s: ", ".join(sorted(set(s.astype(str))))),
        Dias_Pagados_Prom=("Dias_Pagados", "mean"),
    ).reset_index()
    agg["Valor"] = agg["Valor"].round(0)
    return agg, missing

def build_ibc(base: pd.DataFrame, smmlv: float) -> pd.DataFrame:
    if base.empty or "Base_IBC" not in base.columns:
        return pd.DataFrame()
    ibc_src = base[base["Base_IBC"].fillna(False)].copy()
    if ibc_src.empty:
        return pd.DataFrame()
    ibc = ibc_src.groupby(["Periodo", "SAP", "Nombre", "CECO", "Tipo_CECO", "Cargo", "Area_Nomina"], as_index=False).agg(
        IBC_Preliminar=("Valor", "sum"),
        Conceptos_IBC=("Concepto", lambda s: ", ".join(sorted(set(s.astype(str))))),
    )
    exo = base[base["Base_Exoneracion"].fillna(False)].groupby("SAP")["Valor"].sum() if "Base_Exoneracion" in base.columns else pd.Series(dtype=float)
    ibc["Devengo_Para_Exoneracion"] = ibc["SAP"].map(exo).fillna(0)
    ibc["Menor_10_SMMLV"] = ibc["Devengo_Para_Exoneracion"] < 10 * smmlv
    ibc["Nota"] = "Base IBC preliminar según marca DKON. Falta módulo de aportes y exclusiones aprendices/practicantes."
    return ibc

def build_base_flag(base: pd.DataFrame, flag_col: str, value_col: str, concept_col: str) -> pd.DataFrame:
    if base.empty or flag_col not in base.columns:
        return pd.DataFrame()
    src = base[base[flag_col].fillna(False)].copy()
    if src.empty:
        return pd.DataFrame()
    out = src.groupby(["Periodo", "SAP", "Nombre", "CECO", "Tipo_CECO", "Cargo", "Area_Nomina"], as_index=False).agg(
        **{value_col: ("Valor", "sum"), concept_col: ("Concepto", lambda s: ", ".join(sorted(set(s.astype(str)))))}
    )
    out[value_col] = out[value_col].round(0)
    return out

def read_previous_provisions(file) -> pd.DataFrame:
    if file is None:
        return pd.DataFrame()
    df = read_sheet(file)
    c_sap = find_col(df, ["SAP", "Nº pers.", "N° pers.", "Número de personal"], True)
    # Formato largo: SAP | Tipo_Provision | Valor
    c_tipo = find_col(df, ["Tipo Provision", "Tipo_Provision", "Concepto_Provision", "Provision", "Provisión"], False)
    c_val = find_col(df, ["Valor", "Valor provision", "Valor_Provision", "Importe", "Saldo"], False)
    if c_tipo and c_val:
        out = pd.DataFrame({"SAP": df[c_sap].map(to_sap), "Tipo_Provision": df[c_tipo].fillna("").astype(str).str.strip(), "Valor_Provision_Mes_Anterior": df[c_val].map(to_number)})
        return out[(out["SAP"] != "") & (out["Tipo_Provision"] != "")]
    # Formato ancho: SAP | Prima_Ant | Cesantias_Ant | etc.
    candidates = {
        "Prima": ["Prima_Ant", "Prima Ant", "Prima", "Provision Prima", "Provisión Prima"],
        "Cesantias": ["Cesantias_Ant", "Cesantías_Ant", "Cesantias Ant", "Cesantías Ant", "Cesantias", "Cesantías"],
        "Intereses": ["Intereses_Ant", "Intereses Ant", "Intereses", "Intereses Cesantias", "Intereses Cesantías"],
        "Vacaciones": ["Vacaciones_Ant", "Vacaciones Ant", "Vacaciones", "Provision Vacaciones", "Provisión Vacaciones"],
    }
    rows = []
    for tipo, cands in candidates.items():
        col = find_col(df, cands, False)
        if col:
            tmp = pd.DataFrame({"SAP": df[c_sap].map(to_sap), "Tipo_Provision": tipo, "Valor_Provision_Mes_Anterior": df[col].map(to_number)})
            rows.append(tmp)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    return out[(out["SAP"] != "") & (out["Valor_Provision_Mes_Anterior"] != 0)]

def build_summary_hc(md: pd.DataFrame, recl: pd.DataFrame, ret_real: pd.DataFrame, ret_sel: pd.DataFrame) -> pd.DataFrame:
    tipos = ["Tiendas", "Logística", "Admon", "Sin clasificar"]
    base = pd.DataFrame({"Tipo_CECO": tipos})
    hc = md.groupby("Tipo_CECO", as_index=False).agg(HC_MD_Actual=("SAP", "nunique")) if not md.empty else pd.DataFrame(columns=["Tipo_CECO", "HC_MD_Actual"])
    ing = recl.groupby("Tipo_CECO", as_index=False).agg(Ingresos=("SAP", "nunique")) if recl is not None and not recl.empty else pd.DataFrame(columns=["Tipo_CECO", "Ingresos"])
    if ret_real is not None and not ret_real.empty:
        rr = ret_real.merge(md[["SAP", "Tipo_CECO"]], on="SAP", how="left").groupby("Tipo_CECO", as_index=False).agg(Retiros_Reales=("SAP", "nunique"))
    else:
        rr = pd.DataFrame(columns=["Tipo_CECO", "Retiros_Reales"])
    rp = ret_sel.groupby("Tipo_CECO", as_index=False).agg(Retiros_Proyectados=("SAP", "nunique")) if ret_sel is not None and not ret_sel.empty else pd.DataFrame(columns=["Tipo_CECO", "Retiros_Proyectados"])
    out = base.merge(hc, how="left").merge(ing, how="left").merge(rr, how="left").merge(rp, how="left").fillna(0)
    for c in ["HC_MD_Actual", "Ingresos", "Retiros_Reales", "Retiros_Proyectados"]:
        out[c] = out[c].astype(int)
    out["HC_Proyectado"] = out["HC_MD_Actual"] + out["Ingresos"] - out["Retiros_Reales"] - out["Retiros_Proyectados"]
    return out

def build_summary_absences(abs_df: pd.DataFrame, md: pd.DataFrame) -> pd.DataFrame:
    if abs_df is None or abs_df.empty:
        return pd.DataFrame(columns=["Tipo_CECO", "Personas_Ausentismo", "Dias_Ausentismo"])
    tmp = abs_df.merge(md[["SAP", "Tipo_CECO", "CECO"]], on="SAP", how="left")
    tmp["Tipo_CECO"] = tmp["Tipo_CECO"].fillna("Sin clasificar")
    return tmp.groupby("Tipo_CECO", as_index=False).agg(Personas_Ausentismo=("SAP", "nunique"), Dias_Ausentismo=("Dias_Ausentismo", "sum"))

def build_summary_ingresos(recl: pd.DataFrame) -> pd.DataFrame:
    if recl is None or recl.empty:
        return pd.DataFrame(columns=["Tipo_CECO", "Ingresos", "CECOs_Impactados"])
    return recl.groupby("Tipo_CECO", as_index=False).agg(Ingresos=("SAP", "nunique"), CECOs_Impactados=("CECO", "nunique"))

def build_summary_retiros(ret_real: pd.DataFrame, ret_sel: pd.DataFrame, md: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if ret_real is not None and not ret_real.empty:
        rr = ret_real.merge(md[["SAP", "Tipo_CECO"]], on="SAP", how="left").assign(Tipo_Retiro="Real")
        rows.append(rr[["SAP", "Tipo_CECO", "Tipo_Retiro"]])
    if ret_sel is not None and not ret_sel.empty:
        rows.append(ret_sel[["SAP", "Tipo_CECO"]].assign(Tipo_Retiro="Proyectado"))
    if not rows:
        return pd.DataFrame(columns=["Tipo_CECO", "Retiros_Reales", "Retiros_Proyectados", "Total_Retiros"])
    tmp = pd.concat(rows, ignore_index=True)
    piv = tmp.pivot_table(index="Tipo_CECO", columns="Tipo_Retiro", values="SAP", aggfunc="nunique", fill_value=0).reset_index()
    if "Real" not in piv.columns: piv["Real"] = 0
    if "Proyectado" not in piv.columns: piv["Proyectado"] = 0
    piv = piv.rename(columns={"Real": "Retiros_Reales", "Proyectado": "Retiros_Proyectados"})
    piv["Total_Retiros"] = piv["Retiros_Reales"] + piv["Retiros_Proyectados"]
    return piv

def build_alerts(md, base, missing, extras):
    rows = []
    for _, r in md[md["Tipo_CECO"] == "Sin clasificar"].iterrows():
        rows.append({"Tipo": "CECO sin clasificar", "SAP": r["SAP"], "Detalle": r["CECO"], "Valor": None})
    if not base.empty:
        if "Regla_Calculo" in base.columns:
            for _, r in base[base["Regla_Calculo"].isin(["SIN_DKON", "SIN_REGLA"])].iterrows():
                rows.append({"Tipo": "Concepto sin marcación DKON", "SAP": r.get("SAP"), "Detalle": r.get("Concepto"), "Valor": r.get("Valor")})
        if "Origen_Marcacion_DKON" in base.columns:
            fallback = base[base["Origen_Marcacion_DKON"].astype(str).str.contains("Default MVP", na=False)]
            for concepto in sorted(fallback["Concepto"].dropna().unique()):
                rows.append({"Tipo": "DKON sin columnas de bases", "SAP": "", "Detalle": f"{concepto}: usando default MVP", "Valor": None})
    if missing is not None and not missing.empty:
        for _, r in missing.iterrows():
            rows.append({"Tipo": "Concepto sin cuenta DKON", "SAP": r.get("SAP"), "Detalle": f"{r.get('Concepto')} / {r.get('Tipo_CECO')}", "Valor": r.get("Valor")})
    frames = [pd.DataFrame(rows)] + [e for e in extras if e is not None and not e.empty]
    return pd.concat(frames, ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame(columns=["Tipo", "SAP", "Detalle", "Valor"])



# ============================================================
# MOTOR INTEGRAL V1 - MÓDULOS COMPLETOS
# ============================================================

def read_any_file(file, sheet_name=None, preferred_sheets=None):
    """Lee Excel/CSV/TXT. Soporta TXT tipo SAP con tuberías."""
    if file is None:
        return pd.DataFrame()
    name = getattr(file, "name", "").lower()
    data = file.getvalue() if hasattr(file, "getvalue") else open(file, "rb").read()
    bio = io.BytesIO(data)
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        xls = pd.ExcelFile(bio)
        if sheet_name and sheet_name in xls.sheet_names:
            return pd.read_excel(xls, sheet_name=sheet_name, dtype=object)
        candidates = preferred_sheets or ["BASE_CALCULO_PROYECCION", "BASE_DEVENGOS_PROYECTADOS", "BASE_DETALLE_CONCEPTO", "Consolidado__Base", "Sheet1"]
        for sh in candidates:
            if sh in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sh, dtype=object)
                if not df.empty:
                    return df
        for sh in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sh, dtype=object)
            if not df.empty:
                return df
        return pd.DataFrame()
    text = data.decode("latin-1", errors="ignore")
    if "|" in text:
        rows = []
        for ln in text.splitlines():
            if "|" not in ln:
                continue
            parts = [p.strip() for p in ln.strip().strip("|").split("|")]
            if len(parts) <= 2:
                continue
            joined = "".join(parts).replace("-", "").strip()
            if not joined:
                continue
            if all(re.fullmatch(r"[-_ ]*", p or "-") for p in parts):
                continue
            rows.append(parts)
        if rows:
            header_idx = 0
            for i, r in enumerate(rows[:30]):
                jt = norm_text(" ".join(r))
                if any(k in jt for k in ["pers", "importe", "cc-n", "nomina", "desde", "hasta", "fecha"]):
                    header_idx = i
                    break
            header = rows[header_idx]
            body = []
            for r in rows[header_idx+1:]:
                if len(r) == len(header):
                    body.append(r)
            if body:
                return pd.DataFrame(body, columns=header)
    for sep in [";", ",", "\t", "|"]:
        try:
            df = pd.read_csv(io.BytesIO(data), sep=sep, dtype=object, encoding="latin-1")
            if df.shape[1] > 1:
                return df
        except Exception:
            pass
    try:
        return pd.read_csv(io.BytesIO(data), dtype=object, encoding="latin-1")
    except Exception:
        return pd.DataFrame()


def to_rate(x):
    v = to_number(x)
    if v > 1:
        return v / 100.0
    return v


def end_of_month(ts):
    ts = pd.Timestamp(ts)
    return ts + pd.offsets.MonthEnd(0)


def semester_start(eval_date):
    d = pd.Timestamp(eval_date)
    return pd.Timestamp(d.year, 1 if d.month <= 6 else 7, 1)


def year_start(eval_date):
    d = pd.Timestamp(eval_date)
    return pd.Timestamp(d.year, 1, 1)


def days_between_for_area(start, end, area):
    if pd.isna(start) or pd.isna(end):
        return 0
    s = pd.Timestamp(start).normalize(); e = pd.Timestamp(end).normalize()
    if e < s:
        return 0
    a = norm_text(area)
    if "administrativos" in a and "365" not in a:
        # Calendario laboral 30: se aproxima con DAYS360 inclusive.
        return max(0, days360_us(s, e + pd.Timedelta(days=1)))
    return inclusive_days(s, e)


def denominator_for_area(area, period_start, period_end):
    return max(1, days_between_for_area(period_start, period_end, area))


def vac_divisor_for_area(area):
    a = norm_text(area)
    if "administrativos" in a and "365" not in a:
        return 360.0
    return 365.0


def normalize_generic_concept_file(file, fuente, periodo_ini=None, periodo_fin=None, sheet_name=None):
    """Lector de pagos/devengos flexible. Devuelve SAP, Concepto, Texto_Concepto, Valor, Fecha_Pago, Fuente."""
    df = read_any_file(file, sheet_name=sheet_name)
    if df.empty:
        return pd.DataFrame(columns=["SAP","Concepto","Texto_Concepto","Valor","Fecha_Pago","Fuente"])
    df = df.copy(); df.columns = [str(c).strip() for c in df.columns]
    c_sap = find_col(df, ["SAP", "Nº pers.", "Nº pers", "Numero de personal", "Número de personal", "PERNR"], False)
    c_con = find_col(df, ["Concepto", "CC-nómina", "CC-nomina", "CC-n.", "CC-n", "CC nomina", "CC nom", "Cód.Concepto"], False)
    c_text = find_col(df, ["Texto", "Texto_Concepto", "Txt.CC-nóm.", "Txt.CC-nom.", "Texto expl.CC-nómina", "Denominación", "Descripcion", "Descripción"], False)
    c_val = find_col(df, ["Valor", "Importe", "Monto", "Devengo", "Pago", "Valor Proyectado", "Importe_Mensual"], False)
    c_qty = find_col(df, ["Cantidad", "CANT", "Horas", "Días", "Dias"], False)
    c_fecha = find_col(df, ["Fecha pago", "Fecha de pago", "Fecha", "Periodo", "Mes", "Fecha_Pago"], False)
    if not c_sap or not c_con or not c_val:
        return pd.DataFrame(columns=["SAP","Concepto","Texto_Concepto","Valor","Fecha_Pago","Fuente"])
    out = pd.DataFrame({
        "SAP": df[c_sap].map(to_sap),
        "Concepto": df[c_con].map(to_concept),
        "Texto_Concepto": df[c_text].astype(str).fillna("") if c_text else "",
        "Valor": df[c_val].map(to_number),
        "Cantidad": df[c_qty].map(to_number) if c_qty else 0.0,
        "Fecha_Pago": to_datetime_series(df[c_fecha]) if c_fecha else pd.NaT,
        "Fuente": fuente,
    })
    if periodo_ini is not None and periodo_fin is not None and c_fecha:
        # Solo filtra cuando la fecha se pudo interpretar; si no, deja el registro para no perderlo.
        mask_date = out["Fecha_Pago"].notna()
        out = out[(~mask_date) | ((out["Fecha_Pago"] >= pd.Timestamp(periodo_ini)) & (out["Fecha_Pago"] <= pd.Timestamp(periodo_fin)))].copy()
    return out[(out["SAP"] != "") & (out["Concepto"] != "") & (out["Valor"] != 0)].copy()


def dkon_flags_by_concept(dkon):
    if dkon is None or dkon.empty:
        return pd.DataFrame(columns=["Concepto","Base_SS","Ley_1393","Base_Parafiscales","Base_Vacaciones","Base_Prestaciones"])
    flag_cols = ["Base_SS","Ley_1393","Base_Parafiscales","Base_Vacaciones","Base_Prestaciones"]
    tmp = dkon[["Concepto"] + flag_cols].copy()
    for c in flag_cols:
        tmp[c] = tmp[c].map(yes_no)
    # SI si cualquiera de las cuentas/tipos CECO lo marca SI.
    agg = tmp.groupby("Concepto", as_index=False)[flag_cols].agg(lambda s: "SI" if (s == "SI").any() else "NO")
    return agg


def read_base_calculo_existing(file, dkon=None, sheet_name=None):
    df = read_any_file(file, sheet_name=sheet_name, preferred_sheets=["BASE_CALCULO_PROYECCION", "BASE_DETALLE_CONCEPTO", "Tabla Consolidada", "Calculo"])
    if df.empty:
        return pd.DataFrame()
    df = df.copy(); df.columns = [str(c).strip() for c in df.columns]
    c_sap = find_col(df, ["SAP", "Nº pers.", "Nº pers", "Numero de personal", "Número de personal", "PERNR"], False)
    c_con = find_col(df, ["Concepto", "CC-nómina", "CC-nomina", "CC-n.", "CC-n", "Concepto SAP"], False)
    c_val = find_col(df, ["Valor", "Importe", "Valor Proyectado", "Valor_Final", "Importe_Mensual", "Monto"], False)
    if not c_sap or not c_con or not c_val:
        return pd.DataFrame()
    c_name = find_col(df, ["Nombre", "Número de personal", "Empleado", "Nombre empleado"], False)
    c_ceco = find_col(df, ["CECO", "Ce.coste", "Centro de coste", "Centro coste", "Centro de costo"], False)
    c_area = find_col(df, ["Área de nómina", "Area de nomina", "Area_Nomina", "Área nómina"], False)
    c_cargo = find_col(df, ["Cargo", "Función", "Funcion", "Posición", "Posicion"], False)
    c_fuente = find_col(df, ["Fuente", "Origen", "Tipo fuente"], False)
    out = pd.DataFrame({
        "Periodo": "",
        "SAP": df[c_sap].map(to_sap),
        "Nombre": df[c_name].astype(str).fillna("") if c_name else "",
        "Area_Nomina": df[c_area].astype(str).fillna("") if c_area else "",
        "CECO": df[c_ceco].map(to_ceco) if c_ceco else "",
        "Tipo_CECO": "",
        "Centro_Coste": "",
        "Cargo": df[c_cargo].astype(str).fillna("") if c_cargo else "",
        "Nivel": "",
        "Concepto": df[c_con].map(to_concept),
        "Texto_Concepto": "",
        "Fuente": df[c_fuente].astype(str).fillna("Base Proyección Cargada") if c_fuente else "Base Proyección Cargada",
        "Importe_Mensual": df[c_val].map(to_number),
        "Dias_Ausentismo": 0.0,
        "Dias_Pagados": 30.0,
        "Metodo_Dias": "Base cálculo cargada",
        "Valor": df[c_val].map(to_number),
        "Cantidad": 0.0,
    })
    out = out[(out["SAP"] != "") & (out["Concepto"] != "")].copy()
    out["Tipo_CECO"] = out["CECO"].map(classify_ceco)
    return out


def run_module1_projection(files, params):
    """Motor central de devengos: versión robusta basada en V5.2."""
    periodo_ini = pd.Timestamp(params["periodo_ini"])
    periodo_fin = pd.Timestamp(params["periodo_fin"])
    smmlv = float(params.get("smmlv", DEFAULT_SMMLV))
    aux = float(params.get("aux", DEFAULT_AUX_TRANSPORTE))
    seed = int(params.get("seed", 2026))

    dkon = build_dkon_matrix(files["dkon"])
    md = read_md_dimension(files["md_act"])
    md_con = read_md_active_concepts(files["md_act"])
    abs_df = read_absences(files.get("aus")) if files.get("aus") else pd.DataFrame(columns=["SAP", "Dias_Ausentismo"])
    ret_real = read_real_retires(files.get("ret_real")) if files.get("ret_real") else pd.DataFrame(columns=["SAP", "Fecha_Retiro_Real"])
    ret_proy = read_projected_retires(files.get("ret_proy"), periodo_fin) if files.get("ret_proy") else pd.DataFrame()
    prov_ant = read_previous_provisions(files.get("prov_ant")) if files.get("prov_ant") else pd.DataFrame()

    md = apply_real_retires(md, ret_real)
    md, ret_sel, alert_ret = select_projected_retires(md, ret_proy, abs_df, seed)

    ger = read_generic_concept_file(files.get("ger"), "Gerencia Administrativa", periodo_ini, periodo_fin) if files.get("ger") else pd.DataFrame()
    cb = read_generic_concept_file(files.get("cb"), "Compensación y Beneficios", periodo_ini, periodo_fin) if files.get("cb") else pd.DataFrame()
    it14 = read_generic_concept_file(files.get("it14"), "IT14", periodo_ini, periodo_fin, "IT14") if files.get("it14") else pd.DataFrame()
    it15 = read_generic_concept_file(files.get("it15"), "IT15", periodo_ini, periodo_fin, "IT15") if files.get("it15") else pd.DataFrame()
    hp = read_generic_concept_file(files.get("horas"), "Horas pagas del mes", periodo_ini, periodo_fin) if files.get("horas") else pd.DataFrame()

    md, md_con, ger_extra = apply_salary_admin(md, md_con, ger)
    recl_raw = read_recruitment_raw(files.get("recl")) if files.get("recl") else pd.DataFrame()
    recl, missing_salary = assign_recruitment_salary(recl_raw, md)

    base_md, md_days = calc_base_concepts(md, md_con, abs_df, periodo_ini, periodo_fin, smmlv, aux)
    base_ing = calc_recruitment(recl, periodo_ini, periodo_fin, smmlv, aux) if not recl.empty else pd.DataFrame()
    extras = [enrich_extra(x, md, periodo_ini) for x in [ger_extra, cb, it14, it15, hp] if x is not None and not x.empty]
    base_extra = pd.concat(extras, ignore_index=True) if extras else pd.DataFrame()

    parts = [x for x in [base_md, base_ing, base_extra] if x is not None and not x.empty]
    base_raw = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    # Si el usuario tiene un archivo Proyección Costos ya armado, se puede anexar o usar como referencia.
    base_loaded = pd.DataFrame()
    if files.get("base_existente"):
        base_loaded = read_base_calculo_existing(files.get("base_existente"), dkon=dkon)
        if not base_loaded.empty:
            base_loaded["Periodo"] = periodo_ini.strftime("%Y-%m")
            base_raw = pd.concat([base_raw, base_loaded], ignore_index=True)

    base, missing_dkon = attach_dkon_attributes(base_raw, dkon)
    cuentas, _ = homologate(base, dkon)
    ibc_insumo = build_ibc(base, smmlv)
    base_paraf = build_base_flag(base, "Base_Parafiscales", "Base_Parafiscales_Valor", "Conceptos_Parafiscales")
    base_prest = build_base_flag(base, "Base_Prestaciones", "Base_Prestaciones_Valor", "Conceptos_Prestaciones")
    base_vac = build_base_flag(base, "Base_Vacaciones", "Base_Vacaciones_Valor", "Conceptos_Vacaciones")

    resumen_cuenta = cuentas.groupby(["Tipo_CECO", "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON"], as_index=False)["Valor"].sum() if not cuentas.empty else pd.DataFrame()
    resumen_ceco = cuentas.groupby(["Tipo_CECO", "CECO", "Centro_Coste", "Cuenta_DKON", "Texto_Cuenta"], as_index=False)["Valor"].sum() if not cuentas.empty else pd.DataFrame()
    resumen_fuente = base.groupby(["Fuente", "Concepto"], as_index=False)["Valor"].sum() if not base.empty else pd.DataFrame()
    resumen_hc = build_summary_hc(md, recl, ret_real, ret_sel)
    resumen_aus = build_summary_absences(abs_df, md)
    resumen_ing = build_summary_ingresos(recl)
    resumen_ret = build_summary_retiros(ret_real, ret_sel, md)

    comp_md = pd.DataFrame()
    if files.get("md_ant"):
        md_ant = read_md_dimension(files["md_ant"])
        ant = md_ant[["SAP", "Nombre", "CECO", "Tipo_CECO", "Salario_Total_MD", "Cargo"]].rename(columns={"Nombre": "Nombre_Ant", "CECO": "CECO_Ant", "Tipo_CECO": "Tipo_CECO_Ant", "Salario_Total_MD": "Salario_Ant", "Cargo": "Cargo_Ant"})
        act = md[["SAP", "Nombre", "CECO", "Tipo_CECO", "Salario_Total_MD", "Cargo"]].rename(columns={"Nombre": "Nombre_Act", "CECO": "CECO_Act", "Tipo_CECO": "Tipo_CECO_Act", "Salario_Total_MD": "Salario_Act", "Cargo": "Cargo_Act"})
        comp_md = ant.merge(act, on="SAP", how="outer")
        comp_md["Estado"] = comp_md.apply(lambda r: "Nuevo" if pd.isna(r.get("CECO_Ant")) else ("Salida" if pd.isna(r.get("CECO_Act")) else "Continúa"), axis=1)
        comp_md["Dif_Salario"] = comp_md["Salario_Act"].fillna(0) - comp_md["Salario_Ant"].fillna(0)

    alertas = build_alerts(md, base, missing_dkon, [alert_ret])
    if missing_salary is not None and not missing_salary.empty:
        miss = missing_salary.copy(); miss["Tipo"] = "Ingreso sin salario referencia"; miss["SAP"] = ""; miss["Detalle"] = miss.apply(lambda r: f"{r.get('Cargo')} / {r.get('Tipo_CECO')} / {r.get('Area_Nomina')}", axis=1); miss["Valor"] = 0
        alertas = pd.concat([alertas, miss[["Tipo", "SAP", "Detalle", "Valor"]]], ignore_index=True)

    return {
        "MATRIZ_DKON_Y": dkon,
        "MD_NORMALIZADO": md,
        "MD_DIAS_CALCULADOS": md_days,
        "AUSENTISMOS_RESUMEN": abs_df,
        "RETIROS_REALES": ret_real,
        "RETIROS_PROYECTADOS": ret_proy,
        "RETIROS_SELECCIONADOS": ret_sel,
        "INGRESOS_PROYECTADOS": recl,
        "NOVEDADES_GERENCIA": ger,
        "COMP_BENEFICIOS": cb,
        "IT14_FILTRADO": it14,
        "IT15_FILTRADO": it15,
        "HORAS_PAGAS_MES": hp,
        "BASE_EXISTENTE_CARGADA": base_loaded,
        "PROVISIONES_MES_ANT": prov_ant,
        "BASE_CALCULO_PROYECCION": base,
        "BASE_CUENTAS_DKON": cuentas,
        "BASE_IBC_INSUMO": ibc_insumo,
        "BASE_PARAFISCALES_INSUMO": base_paraf,
        "BASE_PRESTACIONES_INSUMO": base_prest,
        "BASE_VACACIONES_INSUMO": base_vac,
        "RESUMEN_CUENTA_DEVENGOS": resumen_cuenta,
        "RESUMEN_CECO_DEVENGOS": resumen_ceco,
        "RESUMEN_FUENTE": resumen_fuente,
        "RESUMEN_HC": resumen_hc,
        "RESUMEN_AUSENTISMOS": resumen_aus,
        "RESUMEN_INGRESOS": resumen_ing,
        "RESUMEN_RETIROS": resumen_ret,
        "COMPARATIVO_MD": comp_md,
        "ALERTAS_MODULO1": alertas,
    }


def read_risk_by_cargo(file, sheet_name=None):
    df = read_any_file(file, sheet_name=sheet_name)
    if df.empty:
        return pd.DataFrame(columns=["Cargo_Key","Cargo_Riesgo_Original","Clase_Riesgo","Tarifa_ARL"])
    df = df.copy(); df.columns = [str(c).strip() for c in df.columns]
    c_key = find_col(df, ["Cargo", "Función", "Funcion", "Posición", "Posicion", "Cargo homologado", "Cargo_Homologado"], False)
    c_class = find_col(df, ["Clase riesgo", "Clase de riesgo", "Riesgo", "Nivel riesgo"], False)
    c_rate = find_col(df, ["Tarifa ARL", "% ARL", "Porcentaje ARL", "Tasa ARL", "ARL"], False)
    if not c_key or not c_rate:
        return pd.DataFrame(columns=["Cargo_Key","Cargo_Riesgo_Original","Clase_Riesgo","Tarifa_ARL"])
    out = pd.DataFrame({
        "Cargo_Key": df[c_key].map(norm_key),
        "Cargo_Riesgo_Original": df[c_key].astype(str).fillna(""),
        "Clase_Riesgo": df[c_class].astype(str).fillna("") if c_class else "",
        "Tarifa_ARL": df[c_rate].map(to_rate),
    })
    return out[out["Cargo_Key"] != ""].drop_duplicates("Cargo_Key", keep="first")


def find_dkon_calc_account(dkon, tipo_ceco, concept_calc, user_key=""):
    sub = dkon[dkon["Tipo_CECO"].eq(tipo_ceco)].copy() if dkon is not None and not dkon.empty else pd.DataFrame()
    if sub.empty:
        return {"Cuenta_DKON":"", "Texto_Cuenta":"", "Grupo_DKON":"", "Concepto_DKON":"", "Metodo_Cuenta":"Sin tipo CECO en DKON"}
    key = norm_key(user_key)
    if key:
        exact = sub[sub["Concepto"].map(norm_key).eq(key)]
        if not exact.empty:
            r = exact.iloc[0]
            return {"Cuenta_DKON":r["Cuenta_DKON"], "Texto_Cuenta":r["Texto_Cuenta"], "Grupo_DKON":r["Grupo_DKON"], "Concepto_DKON":r["Concepto"], "Metodo_Cuenta":"Código usuario"}
        mask = sub.apply(lambda r: key in norm_key(str(r.get("Texto_Concepto_DKON", "")) + " " + str(r.get("Texto_Cuenta", "")) + " " + str(r.get("Descripcion_DKON", ""))), axis=1)
        found = sub[mask]
        if not found.empty:
            r = found.iloc[0]
            return {"Cuenta_DKON":r["Cuenta_DKON"], "Texto_Cuenta":r["Texto_Cuenta"], "Grupo_DKON":r["Grupo_DKON"], "Concepto_DKON":r["Concepto"], "Metodo_Cuenta":"Texto usuario"}
    keywords = {
        "Salud empresa":["salud","eps"], "Pensión empresa":["pension"], "ARL":["arl","riesgo"],
        "Caja compensación":["caja","compensacion","ccf"], "SENA":["sena"], "ICBF":["icbf"],
        "Prima":["prima"], "Cesantías":["cesantia","cesantias"], "Intereses cesantías":["interes","cesantia"], "Vacaciones":["vacacion","vacaciones"]
    }.get(concept_calc, [])
    if keywords:
        def has_kw(r):
            t = norm_text(str(r.get("Texto_Concepto_DKON", "")) + " " + str(r.get("Texto_Cuenta", "")) + " " + str(r.get("Descripcion_DKON", "")) + " " + str(r.get("Grupo_DKON", "")))
            return all(k in t for k in keywords) if concept_calc == "Intereses cesantías" else any(k in t for k in keywords)
        found = sub[sub.apply(has_kw, axis=1)]
        if not found.empty:
            r = found.iloc[0]
            return {"Cuenta_DKON":r["Cuenta_DKON"], "Texto_Cuenta":r["Texto_Cuenta"], "Grupo_DKON":r["Grupo_DKON"], "Concepto_DKON":r["Concepto"], "Metodo_Cuenta":"Keyword DKON"}
    return {"Cuenta_DKON":"", "Texto_Cuenta":"", "Grupo_DKON":"", "Concepto_DKON":"", "Metodo_Cuenta":"No encontrado"}


def calculate_seguridad_social(base, dkon, risk_file=None, params=None, dkon_keys=None):
    params = params or {}; dkon_keys = dkon_keys or {}
    smmlv = float(params.get("smmlv", DEFAULT_SMMLV))
    rates = {
        "Salud empresa": float(params.get("rate_salud", 0.085)),
        "Pensión empresa": float(params.get("rate_pension", 0.12)),
        "Caja compensación": float(params.get("rate_caja", 0.04)),
        "SENA": float(params.get("rate_sena", 0.02)),
        "ICBF": float(params.get("rate_icbf", 0.03)),
    }
    use_ley = bool(params.get("use_ley1393", True))
    apply_exo = bool(params.get("apply_exoneration", True))
    apply_min_ibc = bool(params.get("apply_min_ibc", False))
    risks = read_risk_by_cargo(risk_file) if risk_file else pd.DataFrame()
    ibc = build_ibc_social(base, use_ley, smmlv, apply_min_ibc)
    if not risks.empty:
        ibc["Cargo_Key"] = ibc["Cargo"].map(norm_key)
        ibc = ibc.merge(risks, on="Cargo_Key", how="left")
    else:
        ibc["Cargo_Riesgo_Original"] = ""; ibc["Clase_Riesgo"] = ""; ibc["Tarifa_ARL"] = np.nan
    rows = []; alerts = []
    for _, r in ibc.iterrows():
        tipo = r.get("Tipo_CECO", "")
        base_ss = float(r.get("IBC_SS", 0) or 0)
        base_para = float(r.get("IBC_Parafiscales", 0) or 0)
        dev_total = float(r.get("Devengo_Total_Proyectado", 0) or 0)
        aprendiz = is_apprentice_like(r)
        exonerado = apply_exo and (dev_total < 10 * smmlv) and (not aprendiz)
        concepts = [
            ("Salud empresa", base_ss, 0.0 if exonerado else rates["Salud empresa"], "Seguridad social"),
            ("Pensión empresa", base_ss, rates["Pensión empresa"], "Seguridad social"),
            ("ARL", base_ss, float(r.get("Tarifa_ARL", 0) or 0), "Seguridad social"),
            ("Caja compensación", base_para, rates["Caja compensación"], "Parafiscales"),
            ("SENA", base_para, 0.0 if exonerado or aprendiz else rates["SENA"], "Parafiscales"),
            ("ICBF", base_para, 0.0 if exonerado or aprendiz else rates["ICBF"], "Parafiscales"),
        ]
        if base_ss > 0 and (pd.isna(r.get("Tarifa_ARL")) or float(r.get("Tarifa_ARL", 0) or 0) <= 0):
            alerts.append({"Tipo":"ARL", "Severidad":"Alta", "SAP":r.get("SAP"), "Detalle":f"Sin tarifa ARL para cargo {r.get('Cargo')}", "Valor":base_ss})
        for calc, ibc_base, rate, fuente in concepts:
            if ibc_base <= 0:
                continue
            valor = round(float(ibc_base) * float(rate), 0)
            acct = find_dkon_calc_account(dkon, tipo, calc, dkon_keys.get(calc, ""))
            rec = {
                "Periodo": params.get("periodo", ""), "SAP":r.get("SAP"), "Nombre":r.get("Nombre"), "CECO":r.get("CECO"), "Tipo_CECO":tipo,
                "Area_Nomina":r.get("Area_Nomina"), "Cargo":r.get("Cargo"), "Concepto_Calculo":calc, "Fuente":fuente,
                "IBC":ibc_base, "Tarifa":rate, "Valor":valor, "Exonerado_10_SMMLV": "SI" if exonerado else "NO", "Aprendiz_Practicante": "SI" if aprendiz else "NO",
                "Clase_Riesgo":r.get("Clase_Riesgo", ""), "Tarifa_ARL":r.get("Tarifa_ARL", ""),
                **acct,
            }
            rows.append(rec)
            if not acct.get("Cuenta_DKON"):
                alerts.append({"Tipo":"Cuenta DKON", "Severidad":"Alta", "SAP":r.get("SAP"), "Detalle":f"Sin cuenta para {calc} / {tipo}", "Valor":valor})
    calc = pd.DataFrame(rows)
    alerts = pd.DataFrame(alerts)
    detail = base[["SAP","Nombre","CECO","Tipo_CECO","Area_Nomina","Cargo","Concepto","Texto_Concepto","Fuente","Valor","Base_SS","Ley_1393","Base_Parafiscales","Cuenta_DKON","Texto_Cuenta"]].copy() if not base.empty else pd.DataFrame()
    return {"BASE_IBC_EMPLEADO": ibc, "DETALLE_IBC_CONCEPTOS": detail, "BASE_SEGURIDAD_SOCIAL": calc[calc["Fuente"].eq("Seguridad social")].copy() if not calc.empty else pd.DataFrame(), "BASE_PARAFISCALES": calc[calc["Fuente"].eq("Parafiscales")].copy() if not calc.empty else pd.DataFrame(), "BASE_FINAL_SS_PARAF": calc, "ALERTAS_SS": alerts}


def read_historical_salaries(file, sheet_name=None):
    df = read_any_file(file, sheet_name=sheet_name)
    if df.empty:
        return pd.DataFrame(columns=["SAP","Nombre_Hist","Desde","Hasta","Concepto","Texto_Concepto","Importe","Area_Nomina_Hist"])
    df = df.copy(); df.columns = [str(c).strip() for c in df.columns]
    c_sap = find_col(df, ["SAP", "Nº pers.", "Nº pers", "Numero de personal", "Número de personal", "PERNR"], False)
    c_name = find_col(df, ["Nombre", "Número de personal", "Empleado"], False)
    c_desde = find_col(df, ["Desde", "Fecha desde", "Inicio"], False)
    c_hasta = find_col(df, ["Hasta", "Fecha hasta", "Fin"], False)
    c_val = find_col(df, ["Importe", "Valor", "Monto", "Salario"], False)
    c_con = find_col(df, ["CC-nómina", "CC-nomina", "CC-n.", "Concepto", "Concepto SAP"], False)
    c_area = find_col(df, ["Área de nómina", "Area de nomina", "Area_Nomina", "Área nómina"], False)
    if not c_sap or not c_desde or not c_hasta or not c_val or not c_con:
        return pd.DataFrame(columns=["SAP","Nombre_Hist","Desde","Hasta","Concepto","Texto_Concepto","Importe","Area_Nomina_Hist"])
    out = pd.DataFrame({
        "SAP": df[c_sap].map(to_sap), "Nombre_Hist": df[c_name].astype(str).fillna("") if c_name else "",
        "Desde": to_datetime_series(df[c_desde]), "Hasta": to_datetime_series(df[c_hasta]),
        "Concepto": df[c_con].map(to_concept), "Texto_Concepto": df[c_con].astype(str).fillna(""),
        "Importe": df[c_val].map(to_number), "Area_Nomina_Hist": df[c_area].astype(str).fillna("") if c_area else "",
    })
    out.loc[out["Hasta"].dt.year >= 9999, "Hasta"] = pd.Timestamp("2099-12-31")
    return out[(out["SAP"] != "") & out["Desde"].notna() & out["Hasta"].notna() & (out["Importe"] != 0)].copy()


def build_prestaciones_bases(base, md, dkon, cwtr_file=None, hist_file=None, params=None):
    """Bases y rastreo para prima / cesantías. No calcula vacaciones."""
    params = params or {}
    eval_date = pd.Timestamp(params.get("fecha_eval"))
    sem_ini = semester_start(eval_date)
    year_ini = year_start(eval_date)
    dkon_flags = dkon_flags_by_concept(dkon)
    cwtr = normalize_generic_concept_file(cwtr_file, "CWTR acumulados") if cwtr_file else pd.DataFrame(columns=["SAP","Concepto","Texto_Concepto","Valor","Fecha_Pago","Fuente"])
    if not cwtr.empty:
        cwtr = cwtr.merge(dkon_flags, on="Concepto", how="left")
        for c in ["Base_SS","Ley_1393","Base_Parafiscales","Base_Vacaciones","Base_Prestaciones"]:
            cwtr[c] = cwtr[c].fillna("NO").map(yes_no)
    hist = read_historical_salaries(hist_file) if hist_file else pd.DataFrame()
    # proyectado del mes desde módulo 1 también entra al corte si aplica a prestaciones.
    proyectado = base[["SAP","Concepto","Texto_Concepto","Valor","Fuente","Base_Prestaciones","Base_Vacaciones"]].copy() if not base.empty else pd.DataFrame()
    if not proyectado.empty:
        proyectado["Fecha_Pago"] = eval_date
        proyectado["Origen"] = "Proyección mes actual"
    rows_prima=[]; rows_ces=[]; rast_cwtr=[]; rast_hist=[]
    md_iter = md.copy()
    for _, emp in md_iter.iterrows():
        sap = emp.get("SAP")
        ingreso = pd.Timestamp(emp.get("Fecha_Ingreso")) if pd.notna(emp.get("Fecha_Ingreso")) else year_ini
        area = emp.get("Area_Nomina", "")
        p_ini = max(sem_ini, ingreso)
        c_ini = max(year_ini, ingreso)
        p_days = denominator_for_area(area, p_ini, eval_date)
        c_days = denominator_for_area(area, c_ini, eval_date)
        # CWTR variable
        emp_cw = cwtr[cwtr["SAP"].eq(sap)].copy() if not cwtr.empty else pd.DataFrame()
        if not emp_cw.empty:
            emp_cw["Fecha_Pago"] = pd.to_datetime(emp_cw["Fecha_Pago"], errors="coerce")
            emp_cw["Fecha_Ingreso"] = ingreso
            emp_cw["Entra_Prima"] = np.where((emp_cw["Base_Prestaciones"].eq("SI")) & (emp_cw["Fecha_Pago"].notna()) & (emp_cw["Fecha_Pago"] >= p_ini) & (emp_cw["Fecha_Pago"] <= eval_date) & (emp_cw["Fecha_Pago"] >= ingreso), "SI", "NO")
            emp_cw["Entra_Cesantias"] = np.where((emp_cw["Base_Prestaciones"].eq("SI")) & (emp_cw["Fecha_Pago"].notna()) & (emp_cw["Fecha_Pago"] >= c_ini) & (emp_cw["Fecha_Pago"] <= eval_date) & (emp_cw["Fecha_Pago"] >= ingreso), "SI", "NO")
            emp_cw["Motivo"] = np.where(emp_cw["Base_Prestaciones"].ne("SI"), "No marcado Base Prestaciones en DKON", np.where(emp_cw["Fecha_Pago"] < ingreso, "Fecha pago menor a fecha ingreso", "Validado"))
            rast_cwtr.append(emp_cw)
        var_prima = emp_cw.loc[emp_cw["Entra_Prima"].eq("SI"), "Valor"].sum() if not emp_cw.empty else 0.0
        var_ces = emp_cw.loc[emp_cw["Entra_Cesantias"].eq("SI"), "Valor"].sum() if not emp_cw.empty else 0.0
        # Proyectado mes actual marcado en DKON como prestaciones entra en ambas bases si fecha evaluación lo contiene.
        emp_proj = proyectado[proyectado["SAP"].eq(sap)].copy() if not proyectado.empty else pd.DataFrame()
        var_proj = emp_proj.loc[emp_proj["Base_Prestaciones"].eq("SI"), "Valor"].sum() if not emp_proj.empty else 0.0
        var_prima += var_proj; var_ces += var_proj
        # Histórico fijo solamente se rastrea y se usa para part time por conceptos de salario part time.
        fixed_prima = 0.0; fixed_ces = 0.0
        emp_hist = hist[hist["SAP"].eq(sap)].copy() if not hist.empty else pd.DataFrame()
        if not emp_hist.empty:
            emp_hist["Area_Nomina_MD"] = area
            emp_hist["Fecha_Ingreso_MD"] = ingreso
            emp_hist["Aplica_Historico"] = np.where(emp_hist["Concepto"].isin(["Y011","Y090"]), "SI", "NO")
            for _, h in emp_hist.iterrows():
                for calc_name, ini, days_total in [("Prima", p_ini, p_days), ("Cesantias", c_ini, c_days)]:
                    s = max(pd.Timestamp(h["Desde"]), ini, ingreso)
                    e = min(pd.Timestamp(h["Hasta"]), eval_date)
                    dias = days_between_for_area(s, e, area)
                    ponderado = float(h["Importe"] or 0) * dias / max(days_total, 1) if h["Aplica_Historico"] == "SI" else 0.0
                    if calc_name == "Prima": fixed_prima += ponderado
                    else: fixed_ces += ponderado
                    rast_hist.append({"SAP":sap, "Nombre":emp.get("Nombre"), "Area_Nomina":area, "Calculo":calc_name, "Concepto":h["Concepto"], "Texto_Concepto":h["Texto_Concepto"], "Desde_Tramo":s, "Hasta_Tramo":e, "Dias_Tramo":dias, "Dias_Base":days_total, "Importe":h["Importe"], "Aplica_Historico":h["Aplica_Historico"], "Valor_Ponderado":ponderado})
        prom_prima = fixed_prima + (var_prima / max(p_days, 1) * 30.0)
        prom_ces = fixed_ces + (var_ces / max(c_days, 1) * 30.0)
        base_common = {"SAP":sap, "Nombre":emp.get("Nombre"), "CECO":emp.get("CECO"), "Tipo_CECO":emp.get("Tipo_CECO"), "Area_Nomina":area, "Cargo":emp.get("Cargo"), "Fecha_Ingreso":ingreso, "Fecha_Evaluacion":eval_date}
        rows_prima.append({**base_common, "Inicio_Ventana":p_ini, "Fin_Ventana":eval_date, "Dias_Base":p_days, "Fijo_PartTime_Ponderado":fixed_prima, "Variable_CWTR_Semestre_y_Proy":var_prima, "Promedio_Prima":prom_prima})
        rows_ces.append({**base_common, "Inicio_Ventana":c_ini, "Fin_Ventana":eval_date, "Dias_Base":c_days, "Fijo_PartTime_Ponderado":fixed_ces, "Variable_CWTR_Anio_y_Proy":var_ces, "Promedio_Cesantias":prom_ces})
    return {"BASE_PROMEDIO_PRIMA": pd.DataFrame(rows_prima), "BASE_PROMEDIO_CESANTIAS": pd.DataFrame(rows_ces), "RASTREO_CWTR_VARIABLE": pd.concat(rast_cwtr, ignore_index=True) if rast_cwtr else pd.DataFrame(), "RASTREO_HISTORICO_SALARIO": pd.DataFrame(rast_hist)}


def read_simple_value_by_sap(file, value_names, sheet_name=None):
    df = read_any_file(file, sheet_name=sheet_name)
    if df.empty:
        return pd.DataFrame(columns=["SAP","Valor"])
    df = df.copy(); df.columns = [str(c).strip() for c in df.columns]
    c_sap = find_col(df, ["SAP", "Nº pers.", "Nº pers", "Numero de personal", "Número de personal", "PERNR"], False)
    c_val = find_col(df, value_names + ["Valor", "Importe", "Monto", "Base", "Provision", "Provisión"], False)
    if not c_sap or not c_val:
        return pd.DataFrame(columns=["SAP","Valor"])
    return pd.DataFrame({"SAP":df[c_sap].map(to_sap), "Valor":df[c_val].map(to_number)}).groupby("SAP", as_index=False)["Valor"].sum()


def calculate_vacaciones_base(dkon, md_act, md_ant, prov_ant_file, pagos_actual_file, pagos_anio_ant_file, params=None):
    params = params or {}
    dkon_flags = dkon_flags_by_concept(dkon)
    prov = read_simple_value_by_sap(prov_ant_file, ["Base vacaciones mes anterior", "Base_Vacaciones_Mes_Anterior", "Base Vacaciones", "Vacaciones_Ant", "Vacaciones Ant"]) if prov_ant_file else pd.DataFrame(columns=["SAP","Valor"])
    prov = prov.rename(columns={"Valor":"Base_Vacaciones_Mes_Anterior"})
    pagos_act = normalize_generic_concept_file(pagos_actual_file, "Pagos vacaciones mes actual") if pagos_actual_file else pd.DataFrame()
    pagos_old = normalize_generic_concept_file(pagos_anio_ant_file, "Pagos vacaciones mismo mes año anterior") if pagos_anio_ant_file else pd.DataFrame()
    def prep_pagos(df, label):
        if df.empty:
            return pd.DataFrame(columns=["SAP","Variable"]), pd.DataFrame()
        x = df.merge(dkon_flags[["Concepto","Base_Vacaciones"]], on="Concepto", how="left")
        x["Base_Vacaciones"] = x["Base_Vacaciones"].fillna("NO").map(yes_no)
        x["Entra_Vacaciones"] = np.where(x["Base_Vacaciones"].eq("SI"), "SI", "NO")
        x["Motivo"] = np.where(x["Entra_Vacaciones"].eq("SI"), "Concepto DKON Base Vacaciones = SI", "No marcado Base Vacaciones en DKON")
        s = x[x["Entra_Vacaciones"].eq("SI")].groupby("SAP", as_index=False)["Valor"].sum().rename(columns={"Valor":"Variable"})
        return s, x
    var_act, rast_act = prep_pagos(pagos_act, "Actual")
    var_old, rast_old = prep_pagos(pagos_old, "Año anterior")
    act = md_act[["SAP","Nombre","CECO","Tipo_CECO","Area_Nomina","Cargo","Salario_Total_MD"]].copy().rename(columns={"Salario_Total_MD":"Salario_Mes_Actual"}) if not md_act.empty else pd.DataFrame()
    ant = md_ant[["SAP","Salario_Total_MD"]].copy().rename(columns={"Salario_Total_MD":"Salario_Mes_Anterior"}) if not md_ant.empty else pd.DataFrame(columns=["SAP","Salario_Mes_Anterior"])
    out = act.merge(ant, on="SAP", how="left").merge(prov, on="SAP", how="left").merge(var_act.rename(columns={"Variable":"Variable_Mes_Actual_Bruta"}), on="SAP", how="left").merge(var_old.rename(columns={"Variable":"Variable_Mismo_Mes_Anio_Ant_Bruta"}), on="SAP", how="left")
    for c in ["Salario_Mes_Anterior","Base_Vacaciones_Mes_Anterior","Variable_Mes_Actual_Bruta","Variable_Mismo_Mes_Anio_Ant_Bruta"]:
        out[c] = out[c].fillna(0).map(to_number)
    out["Divisor_Vacaciones"] = out["Area_Nomina"].map(vac_divisor_for_area)
    out["Variable_Mes_Actual_Mensualizada"] = out["Variable_Mes_Actual_Bruta"] / out["Divisor_Vacaciones"] * 30
    out["Variable_Mismo_Mes_Anio_Ant_Mensualizada"] = out["Variable_Mismo_Mes_Anio_Ant_Bruta"] / out["Divisor_Vacaciones"] * 30
    out["Base_Vacaciones_Actual"] = out["Base_Vacaciones_Mes_Anterior"] - out["Salario_Mes_Anterior"] - out["Variable_Mismo_Mes_Anio_Ant_Mensualizada"] + out["Variable_Mes_Actual_Mensualizada"] + out["Salario_Mes_Actual"]
    alerts=[]
    alerts += [{"Tipo":"Vacaciones", "Severidad":"Alta", "SAP":r["SAP"], "Detalle":"Sin base/provisión vacaciones mes anterior", "Valor":0} for _, r in out[out["Base_Vacaciones_Mes_Anterior"].eq(0)].iterrows()]
    return {"BASE_VACACIONES_CALCULO": out, "RASTREO_VARIABLE_ACTUAL": rast_act, "RASTREO_VARIABLE_ANIO_ANT": rast_old, "ALERTAS_VACACIONES": pd.DataFrame(alerts)}


def make_accounted_calc_rows(calc_df, dkon, concept_name, value_col, fuente, params=None, dkon_key=""):
    params = params or {}
    rows=[]
    if calc_df is None or calc_df.empty:
        return pd.DataFrame()
    for _, r in calc_df.iterrows():
        val = float(r.get(value_col, 0) or 0)
        if val == 0:
            continue
        acct = find_dkon_calc_account(dkon, r.get("Tipo_CECO", ""), concept_name, dkon_key)
        rows.append({"Periodo":params.get("periodo", ""), "SAP":r.get("SAP"), "Nombre":r.get("Nombre"), "CECO":r.get("CECO"), "Tipo_CECO":r.get("Tipo_CECO"), "Area_Nomina":r.get("Area_Nomina"), "Cargo":r.get("Cargo"), "Concepto_Calculo":concept_name, "Concepto":acct.get("Concepto_DKON", ""), "Fuente":fuente, "Valor":val, **acct})
    return pd.DataFrame(rows)


def consolidate_all_outputs(mod1, ss, prest, vac, params=None, dkon_keys=None):
    params = params or {}; dkon_keys = dkon_keys or {}
    dkon = mod1.get("MATRIZ_DKON_Y", pd.DataFrame())
    base = mod1.get("BASE_CALCULO_PROYECCION", pd.DataFrame()).copy()
    rows=[]
    if not base.empty:
        keep = ["Periodo","SAP","Nombre","CECO","Tipo_CECO","Area_Nomina","Cargo","Concepto","Texto_Concepto","Fuente","Valor","Cuenta_DKON","Texto_Cuenta","Grupo_DKON"]
        for c in keep:
            if c not in base.columns: base[c]=""
        b = base[keep].copy(); b["Concepto_Calculo"] = b["Concepto"]; rows.append(b)
    if ss and not ss.get("BASE_FINAL_SS_PARAF", pd.DataFrame()).empty:
        x = ss["BASE_FINAL_SS_PARAF"].copy()
        x["Concepto"] = x.get("Concepto_DKON", "")
        x["Texto_Concepto"] = x["Concepto_Calculo"]
        rows.append(x[["Periodo","SAP","Nombre","CECO","Tipo_CECO","Area_Nomina","Cargo","Concepto","Texto_Concepto","Concepto_Calculo","Fuente","Valor","Cuenta_DKON","Texto_Cuenta","Grupo_DKON"]])
    if prest:
        prima_acc = make_accounted_calc_rows(prest.get("BASE_PROMEDIO_PRIMA"), dkon, "Prima", "Promedio_Prima", "Prestaciones - Prima base", params, dkon_keys.get("Prima", ""))
        ces_acc = make_accounted_calc_rows(prest.get("BASE_PROMEDIO_CESANTIAS"), dkon, "Cesantías", "Promedio_Cesantias", "Prestaciones - Cesantías base", params, dkon_keys.get("Cesantías", ""))
        for x in [prima_acc, ces_acc]:
            if not x.empty:
                x["Texto_Concepto"] = x["Concepto_Calculo"]
                rows.append(x[["Periodo","SAP","Nombre","CECO","Tipo_CECO","Area_Nomina","Cargo","Concepto","Texto_Concepto","Concepto_Calculo","Fuente","Valor","Cuenta_DKON","Texto_Cuenta","Grupo_DKON"]])
    if vac:
        vac_acc = make_accounted_calc_rows(vac.get("BASE_VACACIONES_CALCULO"), dkon, "Vacaciones", "Base_Vacaciones_Actual", "Vacaciones - base móvil", params, dkon_keys.get("Vacaciones", ""))
        if not vac_acc.empty:
            vac_acc["Texto_Concepto"] = vac_acc["Concepto_Calculo"]
            rows.append(vac_acc[["Periodo","SAP","Nombre","CECO","Tipo_CECO","Area_Nomina","Cargo","Concepto","Texto_Concepto","Concepto_Calculo","Fuente","Valor","Cuenta_DKON","Texto_Cuenta","Grupo_DKON"]])
    final = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not final.empty:
        resumen_cuenta = final.groupby(["Tipo_CECO","Cuenta_DKON","Texto_Cuenta","Grupo_DKON"], as_index=False)["Valor"].sum()
        resumen_ceco = final.groupby(["Tipo_CECO","CECO","Cuenta_DKON","Texto_Cuenta"], as_index=False)["Valor"].sum()
        resumen_fuente = final.groupby(["Fuente"], as_index=False)["Valor"].sum()
    else:
        resumen_cuenta = resumen_ceco = resumen_fuente = pd.DataFrame()
    return {"BASE_FINAL_CONSOLIDADA_DKON": final, "RESUMEN_FINAL_CUENTA": resumen_cuenta, "RESUMEN_FINAL_CECO": resumen_ceco, "RESUMEN_FINAL_FUENTE": resumen_fuente}

# ============================================================
# Override performance: homologación rápida para bases grandes
# ============================================================
def homologate(base: pd.DataFrame, dkon: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if base is None or base.empty:
        return pd.DataFrame(), pd.DataFrame()
    if "Cuenta_DKON" not in base.columns:
        base, missing = attach_dkon_attributes(base, dkon)
    else:
        missing = base[base["Cuenta_DKON"].isna() | (base["Cuenta_DKON"].astype(str).str.strip() == "")].copy()
    ok = base.drop(missing.index, errors="ignore").copy()
    if ok.empty:
        return ok, missing
    gcols = [
        "Periodo", "SAP", "Nombre", "Area_Nomina", "CECO", "Tipo_CECO", "Centro_Coste", "Cargo", "Nivel",
        "Cuenta_DKON", "Texto_Cuenta", "Grupo_DKON", "Fuente",
        "Base_SS", "Ley_1393", "Base_Parafiscales", "Base_Vacaciones", "Base_Prestaciones",
    ]
    for c in gcols:
        if c not in ok.columns:
            ok[c] = ""
    # Evita groupby con lambdas costosas. El detalle por concepto queda en BASE_CALCULO_PROYECCION.
    agg = ok.groupby(gcols, dropna=False, as_index=False).agg(
        Valor=("Valor", "sum"),
        Dias_Pagados_Prom=("Dias_Pagados", "mean"),
    )
    agg["Valor"] = agg["Valor"].round(0)
    return agg, missing
