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
)

st.set_page_config(page_title="Modelo Integral Proyecciones Nómina JMC", page_icon="💼", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.1rem;}
.main-title {font-size:2.0rem;font-weight:850;color:#7c2d12;margin-bottom:.1rem;}
.sub-title {font-size:1rem;color:#57534e;margin-bottom:1.2rem;}
.section-box {border:1px solid #fed7aa;background:#fff7ed;border-radius:14px;padding:12px;margin-bottom:12px;}
div[data-testid="stMetric"] {background:#fff7ed;border:1px solid #fed7aa;padding:12px;border-radius:14px;}
.small-note {font-size:.86rem;color:#78716c;}
.footer {font-size:.82rem;color:#78716c;margin-top:2rem;}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="main-title">💼 Modelo Integral Proyecciones Nómina JMC</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Motor completo por módulos: devengos, validación DKON, seguridad social/parafiscales, prestaciones, vacaciones y consolidación por cuenta.</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Parámetros globales")
    periodo_ini = pd.Timestamp(st.date_input("Fecha inicio periodo", value=date(2026, 6, 1)))
    periodo_fin = pd.Timestamp(st.date_input("Fecha fin periodo", value=date(2026, 6, 30)))
    fecha_eval = pd.Timestamp(st.date_input("Fecha evaluación prestaciones/vacaciones", value=date(2026, 6, 30)))
    smmlv = st.number_input("SMMLV", min_value=0, value=DEFAULT_SMMLV, step=1000, format="%d")
    aux = st.number_input("Auxilio transporte", min_value=0, value=DEFAULT_AUX_TRANSPORTE, step=1000, format="%d")
    seed = st.number_input("Semilla retiros proyectados", min_value=1, value=2026, step=1)

    st.divider()
    st.header("🧮 Seguridad social")
    rate_salud = st.number_input("Salud empresa", min_value=0.0, value=8.5, step=0.1, format="%.3f") / 100
    rate_pension = st.number_input("Pensión empresa", min_value=0.0, value=12.0, step=0.1, format="%.3f") / 100
    rate_caja = st.number_input("Caja compensación", min_value=0.0, value=4.0, step=0.1, format="%.3f") / 100
    rate_sena = st.number_input("SENA", min_value=0.0, value=2.0, step=0.1, format="%.3f") / 100
    rate_icbf = st.number_input("ICBF", min_value=0.0, value=3.0, step=0.1, format="%.3f") / 100
    use_ley1393 = st.checkbox("Aplicar Ley 1393 / 40% no salarial", value=True)
    apply_exoneration = st.checkbox("Aplicar exoneración 10 SMMLV", value=True)
    apply_min_ibc = st.checkbox("Forzar IBC mínimo = SMMLV si hay IBC", value=False)

    st.divider()
    st.header("🔎 Búsqueda cuentas SS/Prestaciones en DKON")
    st.caption("Opcional. Puedes escribir el código DKON exacto o una palabra de búsqueda si el automático no encuentra la cuenta.")
    key_salud = st.text_input("Cuenta/búsqueda Salud", value="")
    key_pension = st.text_input("Cuenta/búsqueda Pensión", value="")
    key_arl = st.text_input("Cuenta/búsqueda ARL", value="")
    key_caja = st.text_input("Cuenta/búsqueda Caja", value="")
    key_sena = st.text_input("Cuenta/búsqueda SENA", value="")
    key_icbf = st.text_input("Cuenta/búsqueda ICBF", value="")
    key_prima = st.text_input("Cuenta/búsqueda Prima", value="")
    key_ces = st.text_input("Cuenta/búsqueda Cesantías", value="")
    key_vac = st.text_input("Cuenta/búsqueda Vacaciones", value="")

st.markdown("### 1) Parametrización y archivos base")
col1, col2, col3, col4 = st.columns(4)
with col1:
    dkon_file = st.file_uploader("DKON enriquecido", type=["xlsx", "xlsm", "xls"], key="dkon")
with col2:
    md_act_file = st.file_uploader("MD mes actual", type=["xlsx", "xlsm", "xls"], key="md_act")
with col3:
    md_ant_file = st.file_uploader("MD mes anterior", type=["xlsx", "xlsm", "xls"], key="md_ant")
with col4:
    base_existente_file = st.file_uploader("Proyección Costos / Base cálculo existente (opcional)", type=["xlsx", "xlsm", "xls"], key="base_existente")

st.markdown("### 2) Módulo 1 · Devengos proyectados")
col1, col2, col3 = st.columns(3)
with col1:
    ger_file = st.file_uploader("Novedades Gerencia Administrativa", type=["xlsx", "xlsm", "xls"], key="ger")
    it14_file = st.file_uploader("IT14", type=["xlsx", "xlsm", "xls"], key="it14")
with col2:
    cb_file = st.file_uploader("Compensación y Beneficios", type=["xlsx", "xlsm", "xls"], key="cb")
    it15_file = st.file_uploader("IT15", type=["xlsx", "xlsm", "xls"], key="it15")
with col3:
    horas_file = st.file_uploader("Horas pagas del mes", type=["xlsx", "xlsm", "xls"], key="horas")
    prov_ant_general_file = st.file_uploader("Provisiones mes anterior general (opcional)", type=["xlsx", "xlsm", "xls"], key="prov_ant_general")

col1, col2, col3, col4 = st.columns(4)
with col1:
    recl_file = st.file_uploader("Ingresos reclutamiento", type=["xlsx", "xlsm", "xls"], key="recl")
with col2:
    aus_file = st.file_uploader("Ausentismos", type=["xlsx", "xlsm", "xls"], key="aus")
with col3:
    ret_real_file = st.file_uploader("Retiros reales", type=["xlsx", "xlsm", "xls"], key="ret_real")
with col4:
    ret_proy_file = st.file_uploader("Retiros proyectados por cargo", type=["xlsx", "xlsm", "xls"], key="ret_proy")

st.markdown("### 3) Módulos posteriores")
col1, col2, col3 = st.columns(3)
with col1:
    risk_file = st.file_uploader("Base riesgos ARL por cargo", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="riesgos")
with col2:
    cwtr_file = st.file_uploader("CWTR / acumulados año actual", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="cwtr")
with col3:
    hist_sal_file = st.file_uploader("Histórico de salarios SAP", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="hist_sal")

st.markdown("### 4) Módulo vacaciones")
col1, col2, col3 = st.columns(3)
with col1:
    prov_vac_ant_file = st.file_uploader("Base/provisión vacaciones mes anterior", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="prov_vac_ant")
with col2:
    pagos_vac_actual_file = st.file_uploader("Pagos Base Vacaciones mes actual", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="pagos_vac_actual")
with col3:
    pagos_vac_anio_ant_file = st.file_uploader("Pagos Base Vacaciones mismo mes año anterior", type=["xlsx", "xlsm", "xls", "csv", "txt"], key="pagos_vac_anio_ant")

st.info("El DKON se usa desde el módulo 1: asigna cuentas por concepto + tipo CECO y marca bases de SS, parafiscales, prestaciones y vacaciones.")

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

run = st.button("🚀 Generar modelo integral", type="primary", use_container_width=True)

if run:
    if not dkon_file or not md_act_file:
        st.error("Carga como mínimo DKON enriquecido y MD mes actual.")
        st.stop()
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
    progress = st.progress(0, text="Iniciando motor...")
    try:
        progress.progress(15, text="Módulo 1: calculando devengos proyectados y cuentas DKON...")
        mod1 = run_module1_projection(files, params)

        progress.progress(35, text="Módulo 3: calculando seguridad social y parafiscales...")
        ss = calculate_seguridad_social(
            mod1["BASE_CALCULO_PROYECCION"],
            mod1["MATRIZ_DKON_Y"],
            risk_file=risk_file,
            params=params,
            dkon_keys=dkon_keys,
        )

        progress.progress(55, text="Módulo 4: armando bases de prima y cesantías...")
        prest = build_prestaciones_bases(
            mod1["BASE_CALCULO_PROYECCION"],
            mod1["MD_NORMALIZADO"],
            mod1["MATRIZ_DKON_Y"],
            cwtr_file=cwtr_file,
            hist_file=hist_sal_file,
            params=params,
        )

        progress.progress(75, text="Módulo 5: calculando base móvil de vacaciones...")
        if md_ant_file and prov_vac_ant_file:
            # Usamos MD anterior normalizado desde el módulo 1 si existe comparativo; se relee para preservar salarios anteriores.
            from engine import read_md_dimension
            md_ant = read_md_dimension(md_ant_file)
            vac = calculate_vacaciones_base(
                mod1["MATRIZ_DKON_Y"],
                mod1["MD_NORMALIZADO"],
                md_ant,
                prov_vac_ant_file,
                pagos_vac_actual_file,
                pagos_vac_anio_ant_file,
                params=params,
            )
        else:
            vac = {"BASE_VACACIONES_CALCULO": pd.DataFrame(), "RASTREO_VARIABLE_ACTUAL": pd.DataFrame(), "RASTREO_VARIABLE_ANIO_ANT": pd.DataFrame(), "ALERTAS_VACACIONES": pd.DataFrame([{"Tipo":"Vacaciones", "Severidad":"Media", "Detalle":"No se cargó MD anterior y/o provisión vacaciones mes anterior. Módulo vacaciones no ejecutado."}])}

        progress.progress(90, text="Consolidando por cuenta DKON...")
        final = consolidate_all_outputs(mod1, ss, prest, vac, params=params, dkon_keys=dkon_keys)

        all_dfs = {}
        all_dfs.update(mod1)
        all_dfs.update(ss)
        all_dfs.update(prest)
        all_dfs.update(vac)
        all_dfs.update(final)
        # Consolidado general de alertas.
        alert_frames = [
            mod1.get("ALERTAS_MODULO1", pd.DataFrame()),
            ss.get("ALERTAS_SS", pd.DataFrame()),
            vac.get("ALERTAS_VACACIONES", pd.DataFrame()),
        ]
        all_dfs["ALERTAS_GENERALES"] = pd.concat([x for x in alert_frames if x is not None and not x.empty], ignore_index=True) if any(x is not None and not x.empty for x in alert_frames) else pd.DataFrame()

        st.session_state["all_dfs"] = all_dfs
        progress.progress(100, text="Modelo integral generado.")
        st.success("Modelo integral generado correctamente.")
    except Exception as e:
        progress.empty()
        st.exception(e)
        st.error("Se presentó un error. Revisa columnas/hojas de los insumos. El módulo es flexible, pero requiere SAP, concepto y valor en las bases de pagos.")

if "all_dfs" in st.session_state:
    dfs = st.session_state["all_dfs"]
    base = dfs.get("BASE_CALCULO_PROYECCION", pd.DataFrame())
    ss_final = dfs.get("BASE_FINAL_SS_PARAF", pd.DataFrame())
    prest_prima = dfs.get("BASE_PROMEDIO_PRIMA", pd.DataFrame())
    vac_base = dfs.get("BASE_VACACIONES_CALCULO", pd.DataFrame())
    final = dfs.get("BASE_FINAL_CONSOLIDADA_DKON", pd.DataFrame())
    alertas = dfs.get("ALERTAS_GENERALES", pd.DataFrame())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Devengos", f"{len(base):,}")
    c2.metric("SS/Paraf", f"{len(ss_final):,}")
    c3.metric("Bases prima", f"{len(prest_prima):,}")
    c4.metric("Vacaciones", f"{len(vac_base):,}")
    c5.metric("Alertas", f"{len(alertas):,}")

    tabs = st.tabs([
        "1 Devengos", "2 SS/Paraf", "3 Prestaciones", "4 Vacaciones", "5 Consolidado", "Resúmenes", "Alertas"
    ])
    with tabs[0]:
        st.dataframe(base.head(500), use_container_width=True)
    with tabs[1]:
        st.write("BASE_IBC_EMPLEADO")
        st.dataframe(dfs.get("BASE_IBC_EMPLEADO", pd.DataFrame()).head(300), use_container_width=True)
        st.write("BASE_FINAL_SS_PARAF")
        st.dataframe(ss_final.head(500), use_container_width=True)
    with tabs[2]:
        st.write("BASE_PROMEDIO_PRIMA")
        st.dataframe(dfs.get("BASE_PROMEDIO_PRIMA", pd.DataFrame()).head(300), use_container_width=True)
        st.write("BASE_PROMEDIO_CESANTIAS")
        st.dataframe(dfs.get("BASE_PROMEDIO_CESANTIAS", pd.DataFrame()).head(300), use_container_width=True)
    with tabs[3]:
        st.write("BASE_VACACIONES_CALCULO")
        st.dataframe(vac_base.head(300), use_container_width=True)
        st.write("RASTREO_VARIABLE_ACTUAL")
        st.dataframe(dfs.get("RASTREO_VARIABLE_ACTUAL", pd.DataFrame()).head(300), use_container_width=True)
    with tabs[4]:
        st.dataframe(final.head(800), use_container_width=True)
    with tabs[5]:
        st.write("Resumen final por cuenta")
        st.dataframe(dfs.get("RESUMEN_FINAL_CUENTA", pd.DataFrame()), use_container_width=True)
        st.write("Resumen final por CECO")
        st.dataframe(dfs.get("RESUMEN_FINAL_CECO", pd.DataFrame()).head(500), use_container_width=True)
        st.write("Headcount / ingresos / retiros / ausentismos")
        r1, r2 = st.columns(2)
        with r1:
            st.dataframe(dfs.get("RESUMEN_HC", pd.DataFrame()), use_container_width=True)
            st.dataframe(dfs.get("RESUMEN_INGRESOS", pd.DataFrame()), use_container_width=True)
        with r2:
            st.dataframe(dfs.get("RESUMEN_RETIROS", pd.DataFrame()), use_container_width=True)
            st.dataframe(dfs.get("RESUMEN_AUSENTISMOS", pd.DataFrame()), use_container_width=True)
    with tabs[6]:
        st.dataframe(alertas, use_container_width=True)

    excel = build_excel(dfs)
    st.download_button(
        "📥 Descargar Excel integral",
        data=excel,
        file_name=f"modelo_integral_proyeccion_nomina_jmc_{periodo_ini.strftime('%Y_%m')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.markdown('<div class="footer">Creado por Andrés Huérfano Dávila - Nómina JMC</div>', unsafe_allow_html=True)
