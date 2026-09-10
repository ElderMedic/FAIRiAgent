# FAIRiAgent documentation catalog

**Canonical map.** Start at the [bilingual front door](README.md) or the
[repository README](../README.md). Do not treat historical plans or archive
notes as the current product contract.

**Last updated:** 2026-09-10

---

## Start here

| Document | Language | Use it for |
|----------|----------|------------|
| [Repository README](../README.md) | EN | Install, run, Web UI |
| [中文快速开始](zh/guides/QUICKSTART.md) | ZH | 安装与第一次跑通 |
| [Architecture & Flow](en/ARCHITECTURE_AND_FLOW.md) | EN | Agents, critic, outputs |
| [系统架构与工作流](zh/ARCHITECTURE_AND_FLOW.md) | ZH | 同上 |
| [Changelog](CHANGELOG.md) | EN | What changed by release |

---

## Use the system

| Document | Language | Use it for |
|----------|----------|------------|
| [LLM Integration](en/LLM_INTEGRATION_GUIDE.md) | EN | Providers, thinking, keys |
| [LLM 集成指南](zh/LLM_INTEGRATION_GUIDE.md) | ZH | 同上 |
| [Source Workspace](en/SOURCE_WORKSPACE.md) | EN | Multi-file inputs and artifacts |
| [Source Workspace](zh/SOURCE_WORKSPACE.md) | ZH | 同上 |
| [Memory](MEMORY_GUIDE.md) | EN | What memory stores and CLI |
| [Mem0 setup](MEM0_QUICKSTART.md) | EN | Install Qdrant / env flags |
| [Mem0 快速开始](zh/guides/MEM0_QUICKSTART.md) | ZH | 记忆层安装 |
| [Docker](en/guides/DOCKER_DEPLOYMENT.md) | EN | Compose stack |
| [LangGraph Studio](en/guides/LANGGRAPH_STUDIO_SETUP.md) | EN | Local graph UI |
| [LangGraph Studio](zh/guides/LANGGRAPH_STUDIO_SETUP.md) | ZH | 同上 |
| [Bioinformatics agentic analysis](en/BIOINFO_AGENTIC_ANALYSIS.md) | EN | BAM/VCF/FASTQ tools |
| [Test guide](zh/guides/TEST_GUIDE.md) | ZH | 跑测试 |

---

## Develop

| Document | Use it for |
|----------|------------|
| [FAIRiAgent REST API](en/development/FAIRIFIER_API_MANUAL.md) | `/api/v1`, SSE, artifacts |
| [FAIR-DS API](en/development/FAIRDS_API_MANUAL.md) | External Data Station |
| [FAIR-DS API（中文）](zh/development/FAIRDS_API_MANUAL.md) | 同上 |
| [Source grounding](en/development/SOURCE_GROUNDING_ARCHITECTURE.md) | Citations, candidate consensus, tests |
| [Prompt engineering](en/development/PROMPT_ENGINEERING_GUIDE.md) | Prompt and context design |
| [LangSmith](en/LANGSMITH_TESTING_GUIDE.md) | Tracing (opt-in) |
| [Critic rubric](en/development/critic_rubric.yaml) | Judge rubric source |
| [Tests](../tests/README.md) | How to run the suite |

Specialized design notes (not onboarding):
[document chunking](en/development/SCIENTIFIC_DOCUMENT_CHUNKING_DESIGN.md),
[hybrid retrieval upgrade plan](en/development/HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md)
(implementation history; env aliases such as `shadow` / `phase4` are **not**
publication condition names).

---

## Evaluate

| Document | Use it for |
|----------|------------|
| [Evaluation methodology](en/EVALUATION_METHODOLOGY.md) | Benchmark v2 scientific contract |
| [Evaluation README](../evaluation/README.md) | Commands, harness, current layout |
| [Harness](../evaluation/harness/README.md) | Manifests and run index |
| [Config](../evaluation/config/README.md) | Env templates and aliases |
| [Expected outcomes](../evaluation/expected_outcomes/README.md) | Local fixture protocol |
| [Dataset notes](../evaluation/datasets/DATASET_README.md) | What the corpus is |
| [Analysis](../evaluation/analysis/README.md) | How to inspect a run |

Campaign scores, dashboards, and manuscript drafts stay local and are not
catalogued here.

---

## Historical (do not use as current contract)

| Location | Why it stays |
|----------|--------------|
| [May 2026 dependency notes](en/guides/DEPENDENCY_UPDATES_MAY2026.md) | One-off upgrade record |
| `evaluation/archive/` | Pre-v2 eval write-ups |
| `evaluation/paper_experiments_v1/` | Phase-0 experiment scripts |
| `evaluation/reports/` | Legacy shared reports |
| `docs/superpowers/` | Dated implementation plans |

---

Local-only notes (gitignored): `docs/en/development/local/`, `docs/manuscript/`.
