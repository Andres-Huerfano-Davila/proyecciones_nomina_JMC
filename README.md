# Modelo Integral Proyecciones Nómina JMC

App Streamlit integral para proyección de costos de nómina JMC.

## Módulos incluidos

1. **Devengos proyectados**: motor central de cálculo con MD, ingresos, retiros, ausentismos, IT14, IT15, C&B, Gerencia, horas pagas y DKON desde el inicio.
2. **Seguridad social y parafiscales**: calcula IBC, Ley 1393, salud, pensión, ARL por cargo, caja, SENA e ICBF.
3. **Prestaciones sociales**: genera bases promedio de prima y cesantías con CWTR, histórico de salarios y fecha de evaluación.
4. **Vacaciones**: calcula base móvil de vacaciones de 12 meses.
5. **Consolidación final**: unifica todos los módulos por SAP + CECO + Tipo CECO + Cuenta DKON + Fuente + Valor.

## Archivos principales

Subir en la raíz del repositorio:

- app.py
- engine.py
- requirements.txt
- runtime.txt
- packages.txt
- README.md

Main file en Streamlit Cloud: `app.py`.
