# FAIRiAgent Phase-0 Experiment Results
# Generated: 2026-05-12
# Total: 190/214 cells OK (89%), 43.6 compute hours

## Per-Condition Summary

| Condition      | Cells     | Avg Fields | Time   |
|---------------|-----------|------------|--------|
| B1 (zero-shot) | 58/58 OK | 117        | 2.7h   |
| B2 (ontology)  | 47/58 OK | 102        | 6.8h   |
| B3 (flat+crit) | 50/58 OK | 31         | 6.2h   |
| Full Pipeline  | 35/40 OK | 74         | 27.9h  |
| **TOTAL**      | **190/214** | —       | **43.6h** |

## Per-Model Matrix (OK cells / total)

Model              B1       B2       B3       Full     Total
─────────────────────────────────────────────────────────────
qwen3.6:27b       10/10    10/10    10/10    8/8      38/40
qwen3.6:35b       10/10    10/10    10/10    8/8      38/40
gemma4:31b        10/10    10/10    10/10    6/8      36/40
DeepSeek-v4        8/8      8/8      8/8      7/8      31/32
gpt-oss:20b       10/10     7/10     8/10     6/8      31/38
qwen3.5:9b        10/10     2/10     4/10     —        16/30
─────────────────────────────────────────────────────────────

## Full Pipeline Avg Fields per Model (successful)
  qwen3.6:27b     8 docs, avg 83 fields
  DeepSeek-v4      7 docs, avg 77 fields
  gemma4:31b       6 docs, avg 74 fields
  gpt-oss:20b      6 docs, avg 71 fields
  qwen3.6:35b      8 docs, avg 66 fields

## B1 Avg Fields per Model (successful)
  qwen3.6:27b     10 docs, avg 137 fields
  qwen3.6:35b     10 docs, avg 126 fields
  gemma4:31b       10 docs, avg 120 fields
  gpt-oss:20b      10 docs, avg 115 fields
  qwen3.5:9b       10 docs, avg 107 fields
  DeepSeek-v4       8 docs, avg  90 fields

## Known Gaps

### Full Pipeline failures (5 cells)
  - deepseek / pea_cold_stress (7200s timeout)
  - gemma4 / arabidopsis (661s)
  - gemma4 / biosensor (164s)
  - gpt-oss / biosensor (364s)
  - gpt-oss / pseudomonas (801s)

### Full Pipeline never run (10 cells)
  - biorem: all 5 models
  - pomato: all 5 models

### Baseline: qwen3.5:9b B2/B3 (14 cells)
  - Model too small for two-step reasoning. Expected, not re-runnable.

### Baseline: gpt-oss B2/B3 (5 cells)
  - Transient JSON errors. Could retry but model inherently unstable.
