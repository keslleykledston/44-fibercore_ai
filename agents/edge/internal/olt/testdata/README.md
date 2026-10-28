# Fixtures SINTÉTICAS

Escritas à mão a partir da estrutura documentada de saída (colunas/rótulos) — **NÃO foram capturadas de equipamento real**.
Seriais, modelos e valores são inventados. Por isso `Registry` mantém `LevelIdentified`: promover a `observed` exige captura
de laboratório sanitizada (`lab_run.md`, `source_refs.md`) conforme `docs/engineering/DRIVER_SDK_INTERFACE.md`.
Se o formato real divergir, os parsers devem ser corrigidos com a fixture real, não o contrário.

**Exceção (captura REAL):** `huawei_ma5608t/MA5600V800R015C00/display_version.txt` vem de equipamento real (ver `lab_run.md` ao lado).
Valida só `Identify` e o transporte; o driver permanece `identified` porque os parsers de ONT continuam sintéticos.
