# FAIRiAgent

FAIRifier Agentic Framework — Software Engineering Spec (LangGraph/LangChain, OSS-first)

0) TL;DR

Build an agentic system that reads scientific literature (PDF/HTML/images), understands the project, retrieves and enriches background knowledge, and auto-drafts a FAIR metadata template + RDF/RO-Crate package for the research. It integrates with FAIR Data Station (FAIR-DS) via API or MCP tools, keeps human-in-the-loop at all critical steps, and is implemented with LangGraph on top of LangChain, using open-source models, parsers, vector DBs, and triple stores.

⸻

## 1) Goals & Scope

	•	Parse papers/proposals/plans (text + figures) → research intent, entities, workflows, datasets, instruments, variables.
	•	Auto-plan which metadata fields are needed; instantiate ISA-Model/FAIR-DS forms and RDF (PROV-O, RO-Crate, DCAT, schema.org, OBO).
	•	Query open knowledge sources (Crossref, OpenAlex, arXiv, Europe PMC, Zenodo, WorkflowHub, MGnify, BioProject/SRA, EBI Ontologies) to fill/validate fields.
	•	Generate:
	•	Metadata Template (CSV/YAML/JSON Schema + SHACL).
	•	RDF graphs (TTL/JSON-LD) + RO-Crate descriptor.
	•	HITL review loops (editable diffs, confidence flags).
	•	Multi-agent plan-execute-monitor; self-critique and tool-use.
	•	Reproducible & auditable (provenance; run logs; versioned artifacts).


## 2) FAIRifier Agentic Framework（精简技术文档）

1. 目标
	•	读取科研文献/计划书（文本+图片），理解研究要素并自动生成：
	•	Metadata 模板（ISA-Model + MIxS；JSON Schema/YAML）
	•	RDF/RO-Crate（schema.org + PROV-O + SHACL）
	•	与 FAIR Data Station（FAIR-DS）/ MCP 交互提交与校验。
	•	全流程 human-in-the-loop（HITL） 审核，保留可追溯证据与决策记录。

2. 架构（OSS 优先）
	•	编排：LangGraph（基于 LangChain 工具/检索）
	•	LLM/Embedding：Qwen2.5-Instruct 或 Mistral-7B；BGE-m3（Apache 2.0）
	•	向量库：Qdrant（默认）/pgvector
	•	三元组/验证：RDFLib + Jena Fuseki（SPARQL），pySHACL
	•	解析：GROBID（PDF 结构化），Tesseract OCR
	•	打包：pyRO-Crate
	•	服务层：FastAPI（API） + Streamlit（HITL）
	•	存储：PostgreSQL（状态/审计）+ MinIO（制品）

3. 关键 Agent（LangGraph 节点）
	•	Planner：分解任务与验收标准（parse → retrieve → map → validate → RDF → submit）
	•	Doc Ingestor：PDF/图片解析与分块
	•	Retriever/Enricher：Qdrant 检索 + 标准/本体检索（FAIRsharing、BioPortal、OpenAlex/Europe PMC 等）
	•	Schema Engineer：选择 MIxS 包，产出 JSON Schema + YAML 模板
	•	RDF Assembler：生成 JSON-LD/Turtle + RO-Crate，写入 PROV-O
	•	Critic：SHACL 校验、术语解析率、置信度门限；必要时转 HITL
	•	FAIR-DS Connector：通过 REST/MCP 创建 Investigation/Study/Assay、上传模板与 RDF

4. 数据流（高层）

上传文档 → 解析分块 → RAG 检索/扩充 → 模板生成 → SHACL 校验 → HITL 审核 → 生成 RDF/RO-Crate → 提交 FAIR-DS → 返回校验报告与持久化证据。

5. 输出制品
	•	template.schema.json（JSON Schema） + template.yaml（可填模板）
	•	graph.ttl/metadata.jsonld（RDF）
	•	ro-crate-metadata.json（RO-Crate）
	•	validation_report.txt（SHACL/FAIR-DS）

6. 最小接口（示例）
	•	POST /projects/run：上传 PDF，启动流程 → 返回校验摘要
	•	GET  /projects/{id}/status：查询状态与问题清单
	•	POST /projects/{id}/hitl-edits：提交人工修改
	•	GET  /projects/{id}/artifacts：下载模板/RDF/RO-Crate

7. 内建规则与记忆
	•	置信度 < 0.75 或必填 MIxS 字段缺失 → 进入 HITL
	•	每个字段必须附带证据 URI + 文本跨度
	•	长期记忆：历史项目的字段选择与本体偏好；在新项目中优先复用

8. 安全与合规
	•	默认本地模型与缓存；禁外呼模式可开关
	•	PII 抑制与日志脱敏；所有工具调用写入 PROV-O 审计
	•	依赖与许可证清单（Apache/MIT 优先）

9. MVP 路线（建议顺序）
	1.	Qdrant + GROBID 接入；文档→分块→检索
	2.	规则+LLM 生成 MIxS 模板（YAML/Schema）
	3.	SHACL 校验 + HITL UI
	4.	产出 RDF/RO-Crate 并对接 FAIR-DS/MCP

10. 最小目录

fairifier/
  apps/api (FastAPI)   apps/ui (Streamlit)
  fairifier/graph (LangGraph 节点与状态)
  fairifier/tools (Qdrant/GROBID/FAIR-DS/SHACL 等)
  kb/schemas & kb/shapes (JSON Schema/SHACL)
  docker/compose.yaml

### Misc

验收与KPI
	•	SHACL 通过率 ≥ 95%，术语可解析率（CURIE/IRI）≥ 95%
	•	关键字段覆盖率（MIxS/ISA 必填）≥ 90%
	•	HITL 平均编辑距离（自动→最终）≤ 15%，单项目总用时 ≤ X 分钟
HITL 策略
	•	置信度阈值 0.75 触发人工审核；所有 PII/许可证/伦理相关字段始终强制 HITL
	•	每个字段保留证据 URI + 文本跨度；审核界面支持“一键跳转证据”
版本与可追溯
	•	对 JSON Schema / SHACL / 映射规则 使用语义化版本（semver），输出制品写入版本号与 Git 提交哈希
	•	RO-Crate 内放入 provenance.json（包含模型、向量器、索引快照、配置哈希）
安全与治理
	•	OIDC + RBAC；工具调用白名单；请求/输出日志脱敏
	•	Prompt 注入防护：RAG sandbox 提示词，外部文本一律当不可信输入处理
测试矩阵（最小集）
	•	解析：长 PDF、扫描件、混合语言
	•	标准映射：MIMAG、MISAG、非宏基因组对照场景
	•	失败场景：缺页/空表/格式异常、API 超时、术语未解析
可扩展点
	•	Package 选择策略可配置（policies/mixs_select.yaml）
	•	工具适配层：搜索/本体/FAIR-DS 连接器皆为可插拔模块
性能预算
	•	首次运行（50–80页 PDF）端到端目标 ≤ 5–8 分钟（CPU+轻量GPU）
	•	Qdrant 采用量化与分段索引；嵌入批量化
“完成的定义”（DoD）
	•	产出 template.schema.json + template.yaml + graph.ttl/jsonld + ro-crate-metadata.json + validation_report
	•	FAIR-DS 返回有效校验 ID；所有制品均有校验和与证据链
