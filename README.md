# Proyección Costos JMC - MVP 2

Esta versión incluye:

- Carga de Dkon.
- Carga de MD Mes Anterior.
- Carga de MD Actual.
- Matriz DKON de conceptos Y.
- Clasificación CECO: 101 = Tiendas, 102 = Logística/CEDIS, 103 = Admon.
- Base detalle por concepto Y.
- Base por cuenta DKON.
- Comparativo MD anterior vs actual.
- Resumen de movimiento de planta.
- Alertas.

## Archivos necesarios

1. `Dkon.XLSX`
2. `MES_ANT.xlsx`
3. `MD_ACTUAL.xlsx`

## Streamlit Cloud

Se incluye `runtime.txt` con `python-3.12` para evitar errores de instalación con Python 3.14 y paquetes como Pillow/pandas.

## Ejecución local

```bash
pip install -r requirements.txt
streamlit run app.py
```
