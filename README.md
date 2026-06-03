# Modelo financiero nómina JMC - MVP 3

Este MVP calcula una primera base financiera de nómina:

- Lee DKON y filtra conceptos Y.
- Lee MD mes actual.
- Calcula conceptos básicos de nómina: Y010, Y011, Y020, Y050, Y051, Y090.
- Calcula auxilio de transporte Y200 según salario y días pagados.
- Descuenta días de ausentismo si se carga el archivo.
- Proyecta ingresos desde archivo de reclutamiento si se carga.
- Homologa cada concepto a cuenta DKON usando Concepto + Tipo CECO.
- Genera detalle por concepto y agrupado por cuenta.

## Archivos mínimos

- DKON
- MD mes actual

## Archivos opcionales

- MD mes anterior
- Ingresos reclutamiento
- Proyección ausentismos

## Despliegue Streamlit Cloud

Main file path: `app.py`
Python: 3.12
