# Fixtures SINTÉTICAS

Escritas à mão a partir da estrutura documentada de saída (colunas/rótulos) — **NÃO foram capturadas de equipamento real**.
Seriais, modelos e valores são inventados. Por isso `Registry` mantém `LevelIdentified`: promover a `observed` exige captura
de laboratório sanitizada (`lab_run.md`, `source_refs.md`) conforme `docs/engineering/DRIVER_SDK_INTERFACE.md`.
Se o formato real divergir, os parsers devem ser corrigidos com a fixture real, não o contrário.

**Exceção (captura REAL):** `huawei_ma5608t/MA5600V800R015C00/display_version.txt` vem de equipamento real (ver `lab_run.md` ao lado).
Valida só `Identify` e o transporte; o driver permanece `identified` porque os parsers de ONT continuam sintéticos.

**Exceção (captura REAL sanitizada):** `datacom_dmos/` vem de OLTs Datacom DmOS reais (2026-11-14, somente leitura). Seriais de ONU trocados por sintéticos (prefixo de 4 letras + contador), chassi zerado; sem IP, MAC nem hostname. Os parsers são golden contra esses arquivos; o nível segue `identified` (faltam PON paginada e ONU com causas de queda).
