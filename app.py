import pandas as pd
import streamlit as st
from datetime import date

from engine import (
    DEFAULT_SMMLV,
    DEFAULT_AUX_TRANSPORTE,
    run_module1_projection,
    calculate_seguridad_social,
    build_prestaciones_bases,
    calculate_vacaciones_base,
    consolidate_all_outputs,
    build_excel,
    uploaded_size_mb,
    read_md_dimension,
)

st.set_page_config(page_title="Modelo Integral Proyecciones Nómina JMC", page_icon="💼", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.0rem;}
.main-title {font-size:2.0rem;font-weight:850;color:#7c2d12;margin-bottom:.1rem;}
.sub-title {font-size:1rem;color:#57534e;margin-bottom:1.0rem;}
.step-box {border:1px solid #fed7aa;background:#fff7ed;border-radius:14px;padding:12px;margin-bottom:12px;}
.ok-box {border:1px solid #bbf7d0;background:#f0fdf4;border-radius:14px;padding:12px;margin-bottom:12px;}
.warn-box {border:1px solid #fde68a;background:#fffbeb;border-radius:14px;padding:12px;margin-bottom:12px;}
div[data-testid="stMetric"] {background:#fff7ed;border:1px solid #fed7aa;padding:12px;border-radius:14px;}
.small-note {font-size:.86rem;color:#78716c;}
.footer {font-size:.82rem;color:#78716c;margin-top:2rem;}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="main-title">💼 Modelo Integral Proyecciones Nómina JMC</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Flujo modular por pestañas: cada módulo calcula su propia salida, con cuentas DKON y trazabilidad.</div>', unsafe_allow_html=True)

# ------------------------------------------------------------
# Helpers UI
# ------------------------------------------------------------

def _empty_df():
    return pd.DataFrame()


def _has_module(name: str) -> bool:
    return name in st.session_state and isinstance(st.session_state[name], dict) and len(st.session_state[name]) > 0


def _download_module(label: str, dfs: dict, filename: str):
    if not dfs:
        return
    try:
        data = build_excel({k: v for k, v in dfs.items() if isinstance(v, pd.DataFrame)})
        st.download_button(
            label,
            data=data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as exc:
        st.warning(f"No pude generar el Excel de descarga: {exc}")


def _preview_df(title: str, df: pd.DataFrame, rows: int = 300):
    st.write(title)
    if df is None or df.empty:
        st.caption("Sin registros todavía.")
    else:
        st.dataframe(df.head(rows), use_container_width=True)


def _module_status(name: str, label: str):
    if _has_module(name):
        st.success(f"{label} generado y guardado en la sesión.")
    else:
        st.info(f"{label} pendiente por ejecutar.")

# ------------------------------------------------------------
# Sidebar global params
# ------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Parámetros globales")
    periodo_ini = pd.Timestamp(st.date_input("Fecha inicio periodo", value=date(2026, 6, 1)))
    periodo_fin = pd.Timestamp(st.date_input("Fecha fin periodo", value=date(2026, 6, 30)))
    fecha_eval = pd.Timestamp(st.date_input("Fecha evaluación", value=date(2026, 6, 30)))
    smmlv = st.number_input("SMMLV", min_value=0, value=DEFAULT_SMMLV, step=1000, format="%d")
    aux = st.number_input("Auxilio transporte", min_value=0, value=DEFAULT_AUX_TRANSPORTE, step=1000, format="%d")
    seed = st.number_input("Semilla retiros proyectados", min_value=1, value=2026, step=1)

    st.divider()
    st.header("🧮 Tarifas SS/parafiscales")
    rate_salud = st.number_input("Salud empresa", min_value=0.0, value=8.5, step=0.1, format="%.3f") / 100
    rate_pension = st.number_input("Pensión empresa", min_value=0.0, value=12.0, step=0.1, format="%.3f") / 100
    rate_caja = st.number_input("Caja compensación", min_value=0.0, value=4.0, step=0.1, format="%.3f") / 100
    rate_sena = st.number_input("SENA", min_value=0.0, value=2.0, step=0.1, format="%.3f") / 100
    rate_icbf = st.number_input("ICBF", min_value=0.0, value=3.0, step=0.1, format="%.3f") / 100
    use_ley1393 = st.checkbox("Aplicar Ley 1393 / 40% no salarial", value=True)
    apply_exoneration = st.checkbox("Aplicar exoneración 10 SMMLV", value=True)
    apply_min_ibc = st.checkbox("Forzar IBC mínimo = SMMLV si hay IBC", value=False)

    st.divider()
    st.header("🔎 Búsqueda cuentas en DKON")
    st.caption("Opcional. Úsalo si la cuenta automática no se encuentra por texto.")
    key_salud = st.text_input("Cuenta/búsqueda Salud", value="")
    key_pension = st.text_input("Cuenta/búsqueda Pensión", value="")
    key_arl = st.text_input("Cuenta/búsqueda ARL", value="")
    key_caja = st.text_input("Cuenta/búsqueda Caja", value="")
    key_sena = st.text_input("Cuenta/búsqueda SENA", value="")
    key_icbf = st.text_input("Cuenta/búsqueda ICBF", value="")
    key_prima = st.text_input("Cuenta/búsqueda Prima", value="")
    key_ces = st.text_input("Cuenta/búsqueda Cesantías", value="")
    key_vac = st.text_input("Cuenta/búsqueda Vacaciones", value="")

params = {
    "periodo_ini": periodo_ini,
    "periodo_fin": periodo_fin,
    "fecha_eval": fecha_eval,
    "periodo": periodo_ini.strftime("%Y-%m"),
    "smmlv": smmlv,
    "aux": aux,
    "seed": seed,
    "rate_salud": rate_salud,
    "rate_pension": rate_pension,
    "rate_caja": rate_caja,
    "rate_sena": rate_sena,
    "rate_icbf": rate_icbf,
    "use_ley1393": use_ley1393,
    "apply_exoneration": apply_exoneration,
    "apply_min_ibc": apply_min_ibc,
}

dkon_keys = {
    "Salud empresa": key_salud,
    "Pensión empresa": key_pension,
    "ARL": key_arl,
    "Caja compensación": key_caja,
    "SENA": key_sena,
    "ICBF": key_icbf,
    "Prima": key_prima,
    "Cesantías": key_ces,
    "Vacaciones": key_vac,
}

st.markdown(
    """
<div class="step-box">
<b>Nuevo flujo:</b> ya no tienes que cargar todo y calcular todo de una vez. Ejecuta cada pestaña por separado.
Si un módulo falla, los módulos ya calculados quedan guardados en la sesión y puedes descargar sus salidas.
</div>
""",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# Main module tabs
# ------------------------------------------------------------
tab_param, tab_mod1, tab_ss, tab_prest, tab_vac, tab_cons, tab_alert = st.tabs([
    "0 Parametrización",
    "1 Devengos proyectados",
    "2 Seguridad social",
    "3 Prestaciones",
    "4 Vacaciones",
    "5 Consolidación",
    "Alertas / control",
])

# ------------------------------------------------------------
# 0 Parametrización
# ------------------------------------------------------------
with tab_param:
    st.subheader("0) Parametrización global")
    st.caption("Estos archivos son base para todos los módulos. El DKON se usa desde el módulo 1 para cuentas y marcas.")
    c1, c2, c3 = st.columns(3)
    with c1:
        dkon_file = st.file_uploader("DKON enriquecido", type=["xlsx", "xlsm", "xls"], key="dkon_param")
    with c2:
        md_act_file = st.file_uploader("MD mes actual", type=["xlsx", "xlsm", "xls"], key="md_act_param")
    with c3:
        md_ant_file = st.file_uploader("MD mes anterior", type=["xlsx", "xlsm", "xls"], key="md_ant_param")

    st.markdown("#### Estado del flujo")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Módulo 1", "OK" if _has_module("mod1") else "Pendiente")
    c2.metric("SS/Paraf", "OK" if _has_module("ss") else "Pendiente")
    c3.metric("Prestaciones", "OK" if _has_module("prest") else "Pendiente")
    c4.metric("Vacaciones", "OK" if _has_module("vac") else "Pendiente")
    c5.metric("Final", "OK" if _has_module("final") else "Pendiente")

    st.info("El resultado de cada módulo se puede descargar dentro de su pestaña. Esto permite comparar contra tu plantilla base antes de seguir.")

# ------------------------------------------------------------
# 1 Devengos proyectados
# ------------------------------------------------------------
with tab_mod1:
    st.subheader("1) Devengos proyectados / cálculo central")
    st.caption("Aquí va el cálculo tipo Proyección Costos: todo lo que la persona ganará o dejará de ganar en el mes. Sale con cuenta DKON desde el inicio.")

    c1, c2, c3 = st.columns(3)
    with c1:
        base_existente_file = st.file_uploader("Proyección Costos / base cálculo existente (opcional)", type=["xlsx", "xlsm", "xls"], key="base_existente_mod1")
        ger_file = st.file_uploader("Novedades Gerencia Administrativa", type=["xlsx", "xlsm", "xls"], key="ger_mod1")
        it14_file = st.file_uploader("IT14", type=["xlsx", "xlsm", "xls"], key="it14_mod1")
    with c2:
        cb_file = st.file_uploader("Compensación y Beneficios", type=["xlsx", "xlsm", "xls"], key="cb_mod1")
        it15_file = st.file_uploader("IT15", type=["xlsx", "xlsm", "xls"], key="it15_mod1")
        horas_file = st.file_uploader("Horas pagas del mes", type=["xlsx", "xlsm", "xls"], key="horas_mod1")
    with c3:
        prov_ant_general_file = st.file_uploader("Provisiones mes anterior general (opcional)", type=["xlsx", "xlsm", "xls"], key="prov_ant_general_mod1")
        recl_file = st.file_uploader("Ingresos reclutamiento", type=["xlsx", "xlsm", "xls"], key="recl_mod1")
        aus_file = st.file_uploader("Ausentismos", type=["xlsx", "xlsm", "xls"], key="aus_mod1")

    c1, c2 = st.columns(2)
    with c1:
        ret_real_file = st.file_uploader("Retiros reales", type=["xlsx", "xlsm", "xls"], key="ret_real_mod1")
    with c2:
        ret_proy_file = st.file_uploader("Retiros proyectados por cargo", type=["xlsx", "xlsm", "xls"], key="ret_proy_mod1")

    if st.button("▶️ Ejecutar módulo 1", type="primary", use_container_width=True):
        if not dkon_file or not md_act_file:
            st.error("Primero carga DKON enriquecido y MD mes actual en la pestaña 0 Parametrización.")
        else:
            files = {
                "dkon": dkon_file,
                "md_act": md_act_file,
                "md_ant": md_ant_file,
                "base_existente": base_existente_file,
                "ger": ger_file,
                "cb": cb_file,
                "horas": horas_file,
                "it14": it14_file,
                "it15": it15_file,
                "recl": recl_file,
                "aus": aus_file,
                "ret_real": ret_real_file,
                "ret_proy": ret_proy_file,
                "prov_ant": prov_ant_general_file,
            }
            with st.spinner("Calculando devengos proyectados y cuentas DKON..."):
                try:
                    st.session_state["mod1"] = run_module1_projection(files, params)
                    st.success("Módulo 1 generado correctamente.")
                except Exception as e:
                    st.exception(e)
                    st.error("El módulo 1 falló. Revisa el archivo señalado; los demás módulos ya calculados no se borran.")

    if _has_module("mod1"):
        mod1 = st.session_state["mod1"]
        base = mod1.get("BASE_CALCULO_PROYECCION", _empty_df())
        cuentas = mod1.get("BASE_CUENTAS_DKON", _empty_df())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Registros base", f"{len(base):,}")
        c2.metric("Registros cuenta", f"{len(cuentas):,}")
        c3.metric("Alertas", f"{len(mod1.get('ALERTAS_MODULO1', _empty_df())):,}")
        c4.metric("Valor devengos", f"{base['Valor'].sum():,.0f}" if not base.empty and "Valor" in base.columns else "0")
        subtabs = st.tabs(["Base cálculo", "Cuentas DKON", "Resúmenes", "Alertas"])
        with subtabs[0]:
            _preview_df("BASE_CALCULO_PROYECCION", base, 500)
        with subtabs[1]:
            _preview_df("BASE_CUENTAS_DKON", cuentas, 500)
        with subtabs[2]:
            _preview_df("RESUMEN_CUENTA_DEVENGOS", mod1.get("RESUMEN_CUENTA_DEVENGOS", _empty_df()))
            _preview_df("RESUMEN_CECO_DEVENGOS", mod1.get("RESUMEN_CECO_DEVENGOS", _empty_df()))
            _preview_df("RESUMEN_HC", mod1.get("RESUMEN_HC", _empty_df()))
            _preview_df("RESUMEN_AUSENTISMOS", mod1.get("RESUMEN_AUSENTISMOS", _empty_df()))
        with subtabs[3]:
            _preview_df("ALERTAS_MODULO1", mod1.get("ALERTAS_MODULO1", _empty_df()))
        _download_module("📥 Descargar salida Módulo 1", mod1, f"modulo_1_devengos_{periodo_ini.strftime('%Y_%m')}.xlsx")

# ------------------------------------------------------------
# 2 Seguridad social
# ------------------------------------------------------------
with tab_ss:
    st.subheader("2) Seguridad social y parafiscales")
    st.caption("Se calcula desde BASE_CALCULO_PROYECCION. La cuenta sale del DKON según concepto de cálculo + tipo CECO: 101→60, 102→62, 103→63.")
    _module_status("mod1", "Módulo 1")
    risk_file = st.file_uploader("Base riesgos ARL por cargo", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="riesgos_ss")

    if st.button("▶️ Ejecutar seguridad social", type="primary", use_container_width=True):
        if not _has_module("mod1"):
            st.error("Primero ejecuta el módulo 1. Seguridad social necesita la base de devengos proyectados.")
        else:
            with st.spinner("Calculando IBC, ARL, salud, pensión y parafiscales..."):
                try:
                    mod1 = st.session_state["mod1"]
                    st.session_state["ss"] = calculate_seguridad_social(
                        mod1["BASE_CALCULO_PROYECCION"],
                        mod1["MATRIZ_DKON_Y"],
                        risk_file=risk_file,
                        params=params,
                        dkon_keys=dkon_keys,
                    )
                    st.success("Módulo seguridad social generado correctamente.")
                except Exception as e:
                    st.exception(e)
                    st.error("El módulo de seguridad social falló. Corrige el insumo de riesgos o DKON y vuelve a ejecutar esta pestaña.")

    if _has_module("ss"):
        ss = st.session_state["ss"]
        c1, c2, c3 = st.columns(3)
        c1.metric("IBC empleados", f"{len(ss.get('BASE_IBC_EMPLEADO', _empty_df())):,}")
        c2.metric("Líneas SS/Paraf", f"{len(ss.get('BASE_FINAL_SS_PARAF', _empty_df())):,}")
        c3.metric("Alertas SS", f"{len(ss.get('ALERTAS_SS', _empty_df())):,}")
        subtabs = st.tabs(["IBC", "Detalle conceptos", "Salida contable", "Alertas"])
        with subtabs[0]:
            _preview_df("BASE_IBC_EMPLEADO", ss.get("BASE_IBC_EMPLEADO", _empty_df()), 500)
        with subtabs[1]:
            _preview_df("DETALLE_IBC_CONCEPTOS", ss.get("DETALLE_IBC_CONCEPTOS", _empty_df()), 500)
        with subtabs[2]:
            _preview_df("BASE_FINAL_SS_PARAF", ss.get("BASE_FINAL_SS_PARAF", _empty_df()), 500)
            _preview_df("RESUMEN_CUENTA", ss.get("RESUMEN_CUENTA", _empty_df()))
        with subtabs[3]:
            _preview_df("ALERTAS_SS", ss.get("ALERTAS_SS", _empty_df()))
        _download_module("📥 Descargar salida Seguridad Social", ss, f"modulo_2_seguridad_social_{periodo_ini.strftime('%Y_%m')}.xlsx")

# ------------------------------------------------------------
# 3 Prestaciones
# ------------------------------------------------------------
with tab_prest:
    st.subheader("3) Prestaciones sociales: prima y cesantías")
    st.caption("No calcula vacaciones. Usa CWTR/acumulados, histórico de salarios cuando aplique, MD y la salida del módulo 1.")
    _module_status("mod1", "Módulo 1")
    c1, c2 = st.columns(2)
    with c1:
        cwtr_file = st.file_uploader("CWTR / acumulados año actual", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="cwtr_prest")
        if cwtr_file is not None and uploaded_size_mb(cwtr_file) >= 80:
            st.warning(f"CWTR grande detectado ({uploaded_size_mb(cwtr_file):,.1f} MB). Se usará lectura liviana y filtro por conceptos DKON de prestaciones.")
    with c2:
        hist_sal_file = st.file_uploader("Histórico de salarios SAP", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="hist_sal_prest")

    if st.button("▶️ Ejecutar prestaciones", type="primary", use_container_width=True):
        if not _has_module("mod1"):
            st.error("Primero ejecuta el módulo 1. Prestaciones necesita MD normalizado, DKON y devengos proyectados.")
        else:
            with st.spinner("Armando bases de prima y cesantías..."):
                try:
                    mod1 = st.session_state["mod1"]
                    st.session_state["prest"] = build_prestaciones_bases(
                        mod1["BASE_CALCULO_PROYECCION"],
                        mod1["MD_NORMALIZADO"],
                        mod1["MATRIZ_DKON_Y"],
                        cwtr_file=cwtr_file,
                        hist_file=hist_sal_file,
                        params=params,
                    )
                    st.success("Módulo prestaciones generado correctamente.")
                except Exception as e:
                    st.exception(e)
                    st.error("El módulo de prestaciones falló. Corrige CWTR/histórico y vuelve a ejecutar esta pestaña.")

    if _has_module("prest"):
        prest = st.session_state["prest"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Bases prima", f"{len(prest.get('BASE_PROMEDIO_PRIMA', _empty_df())):,}")
        c2.metric("Bases cesantías", f"{len(prest.get('BASE_PROMEDIO_CESANTIAS', _empty_df())):,}")
        c3.metric("Rastreo CWTR", f"{len(prest.get('RASTREO_CWTR_VARIABLE', _empty_df())):,}")
        subtabs = st.tabs(["Prima", "Cesantías", "Rastreo CWTR", "Histórico salario"])
        with subtabs[0]:
            _preview_df("BASE_PROMEDIO_PRIMA", prest.get("BASE_PROMEDIO_PRIMA", _empty_df()), 500)
        with subtabs[1]:
            _preview_df("BASE_PROMEDIO_CESANTIAS", prest.get("BASE_PROMEDIO_CESANTIAS", _empty_df()), 500)
        with subtabs[2]:
            _preview_df("RASTREO_CWTR_VARIABLE", prest.get("RASTREO_CWTR_VARIABLE", _empty_df()), 500)
        with subtabs[3]:
            _preview_df("RASTREO_HISTORICO_SALARIO", prest.get("RASTREO_HISTORICO_SALARIO", _empty_df()), 500)
        _download_module("📥 Descargar salida Prestaciones", prest, f"modulo_3_prestaciones_{periodo_ini.strftime('%Y_%m')}.xlsx")

# ------------------------------------------------------------
# 4 Vacaciones
# ------------------------------------------------------------
with tab_vac:
    st.subheader("4) Vacaciones: base móvil 12 meses")
    st.caption("Los pagos Base Vacaciones del mes actual salen del Módulo 1. El usuario solo carga provisión/base anterior y pagos del mismo mes del año anterior.")
    _module_status("mod1", "Módulo 1")
    c1, c2 = st.columns(2)
    with c1:
        prov_vac_ant_file = st.file_uploader("Base/provisión vacaciones mes anterior", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="prov_vac_ant_vac")
    with c2:
        pagos_vac_anio_ant_file = st.file_uploader("Pagos Base Vacaciones mismo mes año anterior", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="pagos_vac_anio_ant_vac")

    st.markdown(
        """
<div class="warn-box">
<b>Fórmula:</b> Base vacaciones actual = Base vacaciones mes anterior - salario mes anterior - variable mismo mes año anterior mensualizada + variable mes actual proyectada mensualizada + salario mes actual.
</div>
""",
        unsafe_allow_html=True,
    )

    if st.button("▶️ Ejecutar vacaciones", type="primary", use_container_width=True):
        if not _has_module("mod1"):
            st.error("Primero ejecuta el módulo 1. Vacaciones necesita los pagos proyectados del mes actual.")
        elif not md_ant_file:
            st.error("Carga MD mes anterior en la pestaña 0 Parametrización para poder restar salario mes anterior.")
        elif not prov_vac_ant_file:
            st.error("Carga la base/provisión vacaciones mes anterior.")
        else:
            with st.spinner("Calculando base móvil de vacaciones..."):
                try:
                    mod1 = st.session_state["mod1"]
                    md_ant = read_md_dimension(md_ant_file)
                    st.session_state["vac"] = calculate_vacaciones_base(
                        mod1["MATRIZ_DKON_Y"],
                        mod1["MD_NORMALIZADO"],
                        md_ant,
                        prov_vac_ant_file,
                        mod1["BASE_CALCULO_PROYECCION"],
                        pagos_vac_anio_ant_file,
                        params=params,
                    )
                    st.success("Módulo vacaciones generado correctamente.")
                except Exception as e:
                    st.exception(e)
                    st.error("El módulo de vacaciones falló. Corrige provisión anterior o pagos año anterior y vuelve a ejecutar esta pestaña.")

    if _has_module("vac"):
        vac = st.session_state["vac"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Bases vacaciones", f"{len(vac.get('BASE_VACACIONES_CALCULO', _empty_df())):,}")
        c2.metric("Rastreo actual", f"{len(vac.get('RASTREO_VARIABLE_ACTUAL', _empty_df())):,}")
        c3.metric("Alertas", f"{len(vac.get('ALERTAS_VACACIONES', _empty_df())):,}")
        subtabs = st.tabs(["Base vacaciones", "Variable actual proyectada", "Variable año anterior", "Alertas"])
        with subtabs[0]:
            _preview_df("BASE_VACACIONES_CALCULO", vac.get("BASE_VACACIONES_CALCULO", _empty_df()), 500)
        with subtabs[1]:
            _preview_df("RASTREO_VARIABLE_ACTUAL", vac.get("RASTREO_VARIABLE_ACTUAL", _empty_df()), 500)
        with subtabs[2]:
            _preview_df("RASTREO_VARIABLE_ANIO_ANT", vac.get("RASTREO_VARIABLE_ANIO_ANT", _empty_df()), 500)
        with subtabs[3]:
            _preview_df("ALERTAS_VACACIONES", vac.get("ALERTAS_VACACIONES", _empty_df()))
        _download_module("📥 Descargar salida Vacaciones", vac, f"modulo_4_vacaciones_{periodo_ini.strftime('%Y_%m')}.xlsx")

# ------------------------------------------------------------
# 5 Consolidación
# ------------------------------------------------------------
with tab_cons:
    st.subheader("5) Consolidación final por cuenta DKON")
    st.caption("Une las salidas que ya tengas calculadas. No obliga a que todos los módulos estén listos, pero el módulo 1 es obligatorio.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Módulo 1", "OK" if _has_module("mod1") else "No")
    c2.metric("SS", "OK" if _has_module("ss") else "No")
    c3.metric("Prestaciones", "OK" if _has_module("prest") else "No")
    c4.metric("Vacaciones", "OK" if _has_module("vac") else "No")

    if st.button("🔗 Consolidar salidas disponibles", type="primary", use_container_width=True):
        if not _has_module("mod1"):
            st.error("Primero ejecuta el módulo 1.")
        else:
            with st.spinner("Consolidando por cuenta DKON..."):
                try:
                    mod1 = st.session_state.get("mod1", {})
                    ss = st.session_state.get("ss", {})
                    prest = st.session_state.get("prest", {})
                    vac = st.session_state.get("vac", {})
                    final = consolidate_all_outputs(mod1, ss, prest, vac, params=params, dkon_keys=dkon_keys)
                    st.session_state["final"] = final
                    all_dfs = {}
                    all_dfs.update(mod1)
                    all_dfs.update(ss)
                    all_dfs.update(prest)
                    all_dfs.update(vac)
                    all_dfs.update(final)
                    alert_frames = [
                        mod1.get("ALERTAS_MODULO1", _empty_df()) if mod1 else _empty_df(),
                        ss.get("ALERTAS_SS", _empty_df()) if ss else _empty_df(),
                        vac.get("ALERTAS_VACACIONES", _empty_df()) if vac else _empty_df(),
                    ]
                    all_dfs["ALERTAS_GENERALES"] = pd.concat([x for x in alert_frames if x is not None and not x.empty], ignore_index=True) if any(x is not None and not x.empty for x in alert_frames) else _empty_df()
                    st.session_state["all_dfs"] = all_dfs
                    st.success("Consolidación generada correctamente.")
                except Exception as e:
                    st.exception(e)
                    st.error("La consolidación falló. Revisa cuentas DKON y módulos disponibles.")

    if _has_module("final"):
        final = st.session_state["final"]
        base_final = final.get("BASE_FINAL_CONSOLIDADA_DKON", _empty_df())
        c1, c2, c3 = st.columns(3)
        c1.metric("Líneas finales", f"{len(base_final):,}")
        c2.metric("Valor final", f"{base_final['Valor'].sum():,.0f}" if not base_final.empty and "Valor" in base_final.columns else "0")
        c3.metric("Cuentas", f"{base_final['Cuenta_DKON'].nunique():,}" if not base_final.empty and "Cuenta_DKON" in base_final.columns else "0")
        subtabs = st.tabs(["Base final", "Resumen cuenta", "Resumen CECO", "Resumen fuente"])
        with subtabs[0]:
            _preview_df("BASE_FINAL_CONSOLIDADA_DKON", base_final, 800)
        with subtabs[1]:
            _preview_df("RESUMEN_FINAL_CUENTA", final.get("RESUMEN_FINAL_CUENTA", _empty_df()), 500)
        with subtabs[2]:
            _preview_df("RESUMEN_FINAL_CECO", final.get("RESUMEN_FINAL_CECO", _empty_df()), 500)
        with subtabs[3]:
            _preview_df("RESUMEN_FINAL_FUENTE", final.get("RESUMEN_FINAL_FUENTE", _empty_df()), 500)

        if "all_dfs" in st.session_state:
            _download_module("📥 Descargar Excel integral completo", st.session_state["all_dfs"], f"modelo_integral_proyeccion_nomina_jmc_{periodo_ini.strftime('%Y_%m')}.xlsx")
        else:
            _download_module("📥 Descargar consolidación final", final, f"consolidado_final_{periodo_ini.strftime('%Y_%m')}.xlsx")

# ------------------------------------------------------------
# Alertas/control
# ------------------------------------------------------------
with tab_alert:
    st.subheader("Alertas y control de calidad")
    frames = []
    if _has_module("mod1"):
        frames.append(st.session_state["mod1"].get("ALERTAS_MODULO1", _empty_df()))
    if _has_module("ss"):
        frames.append(st.session_state["ss"].get("ALERTAS_SS", _empty_df()))
    if _has_module("vac"):
        frames.append(st.session_state["vac"].get("ALERTAS_VACACIONES", _empty_df()))
    alertas = pd.concat([x for x in frames if x is not None and not x.empty], ignore_index=True) if any(x is not None and not x.empty for x in frames) else _empty_df()
    _preview_df("ALERTAS_GENERALES", alertas, 1000)

    st.markdown("#### Descarga rápida por módulo")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if _has_module("mod1"):
            _download_module("Módulo 1", st.session_state["mod1"], f"modulo_1_devengos_{periodo_ini.strftime('%Y_%m')}.xlsx")
    with c2:
        if _has_module("ss"):
            _download_module("SS/Paraf", st.session_state["ss"], f"modulo_2_ss_{periodo_ini.strftime('%Y_%m')}.xlsx")
    with c3:
        if _has_module("prest"):
            _download_module("Prestaciones", st.session_state["prest"], f"modulo_3_prestaciones_{periodo_ini.strftime('%Y_%m')}.xlsx")
    with c4:
        if _has_module("vac"):
            _download_module("Vacaciones", st.session_state["vac"], f"modulo_4_vacaciones_{periodo_ini.strftime('%Y_%m')}.xlsx")

st.markdown('<div class="footer">Creado por Andrés Huérfano Dávila - Nómina JMC</div>', unsafe_allow_html=True)
