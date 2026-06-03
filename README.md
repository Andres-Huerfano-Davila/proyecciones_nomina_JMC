# Proyección de Costos JMC - MVP 1

Primera versión del motor base para convertir conceptos de nómina `Y` en cuentas DKON según el tipo de CECO.

## Regla central

- CECO `101xxxxx` = Tiendas -> cuentas `60...`
- CECO `102xxxxx` = Logística/CEDIS -> cuentas `62...`
- CECO `103xxxxx` = Admon -> cuentas `63...`

La homologación se hace por:

```text
Concepto Y + Tipo CECO = Cuenta DKON
```

## Archivos de entrada mínimos

1. `Dkon.XLSX`
2. `MD_ACTUAL.xlsx`

## Salida

El aplicativo genera un Excel con estas hojas:

- `MATRIZ_DKON_Y`
- `MD_NORMALIZADO_Y`
- `BASE_CONCEPTOS_Y`
- `BASE_CUENTAS_DKON`
- `RESUMEN_TIPO_CECO`
- `RESUMEN_CUENTA`
- `RESUMEN_CECO`
- `ALERTAS`

## Cómo correr localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```
