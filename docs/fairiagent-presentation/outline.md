# FAIRiAgent Academic Presentation — Outline

> **主题**：Amber Scholar — 暖奶油色底、琥珀/棕 accent、serif 标题
> **总时长**：约 25–30 分钟（口播 ~4500 词 ÷ 150 词/分钟）
> **章节数**：18 章 / ~60 步
> **目标**：Seminar talk，混合学术 audience（计算+实验+合成生物学）
> **设计**：图 >60% 面积，heading ≥ 48px，body ≥ 28px，每 slide 一个核心 idea

---

## 素材清单

### 已就绪图片

**概念图** (`docs/fairiagent-presentation/figs/`):
- `LLMvsAgent.png` — LLM vs Agent 范式对比 → Slide 4
- `poster_fig1_architecture_handdrawn_v5.jpg` — graphical abstract 架构图 → Slide 7
- `memory fig.png` — memory 在小模型上的效果 → Slide 10
- `fairds_screenshot.png` — FAIR-DS 界面 → Slide 2

**实验图** (`evaluation/paper_experiments_v1/figures/`):
- `fig3_condition_comparison.png` — Phase-0 四条件对比（主结果）
- `fig4_isa_structure_heatmap.png` — ISA 层热力图
- `presentation/exp1_hierarchical_f1.png` — biosensor+earthworm 子集
- `presentation/exp2_pass_at_k.png` — Pass@k 探索图
- `presentation/exp3_ablation.png` — 消融/质量代理图
- `presentation/poster_fig3_fig4_combined.png` — 组合 panel

Slide 应用通过 `sync_presentation_assets.py` 同步到 `presentation-v2/public/figs/`。

### 需要补的 placeholder
1. Slide 13 — Deep dive trace 数据（LLM 输出片段 + baseline 错误标注；见 `figs/tracingexample.png` 草图）
2. Slide 14/15 — 正式消融与 Pass@k 需 Phase-1/2 重跑后替换 `presentation/exp2_*` / `exp3_*`

---

## 1. title — Title Slide（1 step · ~15s）

**信息池**：
- 项目名：FAIRiAgent
- 副标题：Reconstructing FAIR Metadata Objects with Multi-Agent Workflows

**开发计划**：
- step 1 — 标题大字居中，副标题下方，作者/机构底部。Amber Scholar 暖色背景。

**口播节选**：
> FAIRiAgent: Reconstructing FAIR Metadata Objects with Multi-Agent Workflows.

---

## 2. fair-pain — FAIR by Design — But Difficult in Practice（3 steps · ~120s）

**信息池**：
- FAIR principles: Findable, Accessible, Interoperable, Reusable
- FAIR-DS: community standard for metadata packages and fields
- Pain points: planning what to collect, filling values, learning standards, manual work
- Core question: "how can we make this easier?"

**开发计划**：
- step 1 — 大字标题 "FAIR by Design — But Difficult in Practice"。展示从实验人员视角的痛点流程：planning → filling → submitting（用简单图示）。
- step 2 — FAIR-DS 简介 + 界面截图 placeholder（占画面大面积）。标注 "learning curve" + "manual work"。
- step 3 — 引出核心问题："How can we make this easier?" 大字突出。

**口播节选**：
> FAIR principles tell us data should be Findable, Accessible, Interoperable, and Reusable. But actually producing FAIR-compliant metadata? FAIR-DS provides the standard packages and fields. But the tool itself has a learning curve. So the question becomes: how can we make this easier?

---

## 3. isa-structure — The Target: A 5-Layer ISA Metadata Object（2 steps · ~90s）

**信息池**：
- ISA 5 层：Investigation → Study → ObservationUnit → Sample → Assay
- Single-row: Investigation, Study
- Multi-row: ObservationUnit, Sample, Assay（需要 row binding）
- 核心论点：这不是填表，是结构化对象重建

**开发计划**：
- step 1 — 5 层金字塔/层级图（手绘风格或简洁矢量），占画面 70%。每层标注名称 + single/multi-row 标记。
- step 2 — 在图上 highlight multi-row 的三层，标注 "Row binding is the challenge"。底部一句话："Not a form-filling problem. A structured object reconstruction problem."

**口播节选**：
> FAIR metadata is not a flat table. It's a 5-layer hierarchical object. The first two layers are single-row. The bottom three are multi-row — for every sample, every assay, you need to get the row binding right.

---

## 4. llm-promise — "Outsource the Boring Work" — Can LLMs Help?（2 steps · ~90s）

**信息池**：
- LLM 可以读 paper、提取信息
- "Outsource the boring work instead of your intelligence"
- Paradigm shift: single prompt-response → multi-step auditable workflow
- 嵌入图：`figs/LLMvsAgent.png`

**开发计划**：
- step 1 — 标题大字。左侧展示 "outsource the boring work" 概念。LLMvsAgent.png 占画面右侧 ~55%。
- step 2 — 图下方标注："LLM: one prompt → one answer" vs "Agentic: multi-step → auditable decisions"。引出 transition。

**口播节选**：
> LLMs can read papers and extract information. Why not outsource the boring metadata work? But there's a fundamental difference between asking an LLM to generate text, and asking it to reconstruct a structured metadata object.

---

## 5. llm-falls-short — Why Raw LLM Falls Short（4 steps · ~150s）

**信息池**：
- 失败模式 1：Hallucination — 编造 package 名、accession number（show LLM output snippet）
- 失败模式 2：Context rot — 长文档中遗忘早期信息
- 失败模式 3：No ISA structure — flat generation，无 sheet assignment，无 row binding
- 来源：实际调试中观察到的 LLM 行为

**开发计划**：
- step 1 — 标题 "Why Raw LLM Falls Short"。三个失败模式以三列卡片形式出现在画面上部。
- step 2 — 聚焦 Hallucination，卡片展开，展示 LLM 输出片段（代码块格式），标注 "made-up package name" / "fake accession"。
- step 3 — 聚焦 Context rot，卡片展开，图示：document → LLM → 后半段遗忘前半段信息。
- step 4 — 聚焦 No ISA structure，卡片展开，展示 flat JSON vs structured ISA JSON 对比。

**口播节选**：
> The model invents package names that don't exist. It makes up accession numbers. In a long document, the model forgets early information. The output is flat — fields without sheet assignment, without row binding.

---

## 6. two-tasks — Two Tasks That Fail Differently（3 steps · ~120s）

**信息池**：
- Metadata Schema：package 选择、field 生成、ISA sheet 分配、row 组织
- Value Extraction：field 值、row 归属、source evidence
- 两个 task 失败模式不同，必须分开设计、分开评测
- 术语统一：Metadata Schema / Value Extraction（此后所有 slide 沿用）

**开发计划**：
- step 1 — 标题 "Two Tasks That Fail Differently"。上方两个大色块并排：左 "Metadata Schema" 右 "Value Extraction"。
- step 2 — 左块展开：列出子任务（package selection, field generation, ISA sheet assignment, row organization），每项一个 icon + 关键词。
- step 3 — 右块展开，同样列出子任务。底部一句话：They fail differently → they must be evaluated separately。

**口播节选**：
> Metadata Schema is about structure: which package, which fields, which ISA sheet, which row. Value Extraction is about content: what value, which row, what evidence. These two tasks need to be designed for separately and evaluated separately.

---

## 7. agent-roles — Decomposing into Agent Roles（3 steps · ~150s）

**信息池**：
- Agent roles: Document Parser → Planner → Knowledge Retriever → JSON Generator → Value Mapper
- 每个 agent 后跟 Critic gate
- 核心论点：每个 agent 承担一个可审计的职责，对应一种 failure mode
- 嵌入图：`figs/poster_fig1_architecture_handdrawn_v5.jpg`

**开发计划**：
- step 1 — `poster_fig1_architecture_handdrawn_v5.jpg` 占画面主导（~65%）。标题 "Decomposing into Agent Roles" 在顶部。
- step 2 — 在图上叠加 3–4 个 annotation 气泡，标注关键 agent 对应的 failure mode：Knowledge Retriever → "prevents hallucination"、Critic → "catches errors"、Value Mapper → "binds rows"。
- step 3 — 底部一句话：Each agent addresses one failure mode. Each step is auditable.

**口播节选**：
> Instead of one massive prompt, we decompose into a set of agent roles. Each agent addresses a specific failure mode. After every agent, a Critic evaluates the output. The point is not that we're using more LLM calls — each call has an auditable responsibility.

---

## 8. grounding — Grounding in Community Standards（3 steps · ~120s）

**信息池**：
- FAIR-DS API 作为 live knowledge source
- Agent 主动查询 packages 和 terms
- Grounded vs ungrounded 对比
- 示例：grounded → "Genome" (real package)；ungrounded → "GenomicsCore" (hallucinated)

**开发计划**：
- step 1 — 标题 "Grounding in Community Standards"。上半屏展示 FAIR-DS → Agent 的 query 流程简图。
- step 2 — 并排对比：左 "Without Grounding"（LLM 直接生成，标注 hallucinated terms），右 "With Grounding"（Agent query FAIR-DS → 只生成存在的 terms）。大 contrast。
- step 3 — 底部结论："The difference is not model size. It's access to authoritative sources."

**口播节选**：
> Without grounding, the LLM invents a package called "GenomicsCore" — sounds plausible, doesn't exist. With grounding, the system queries FAIR-DS and correctly selects "Genome." The difference is not about model size. It's about giving the system access to authoritative sources.

---

## 9. critic — Self-Correction: Critic + Rollback（3 steps · ~120s）

**信息池**：
- Critic 决策：ACCEPT / RETRY / ESCALATE
- RETRY 带具体 feedback 回到前序 agent
- Rollback：回到更早状态，重新 retrieval / regeneration
- "不是 try harder，是 try differently"

**开发计划**：
- step 1 — 标题 "Self-Correction: Critic + Rollback"。中间展示 ACCEPT/RETRY/ESCALATE 三态决策图（简单状态机图）。
- step 2 — 在图上展示一个 RETRY 的具体例子：Critic → "missing mandatory field 'collection date'" → agent retries with this feedback → ACCEPT。
- step 3 — 展示 Rollback 路径：agent → critic (fail) → rollback to Knowledge Retriever → re-query → regenerate。标注 "some errors need re-grounding, not just retrying"。

**口播节选**：
> The Critic checks schema compliance, data types, confidence. ACCEPT and move on. RETRY with specific feedback. Some errors can't be fixed by just trying again — the system needs rollback to an earlier state. It's the difference between "try harder" and "try differently."

---

## 10. memory — Session Memory（2 steps · ~90s）

**信息池**：
- 多步 workflow 中 context 退化
- Memory 跨 step 保留上下文：已发现的 evidence、评估过的 packages、仍不确定的 fields
- 对 local models 尤其关键
- 嵌入图：`figs/memory fig.png`

**开发计划**：
- step 1 — `memory fig.png` 占画面主导。标题 "Session Memory" 在顶部。
- step 2 — 一句 takeaway 大字标注在图上："Memory reduces runtime, preserves metadata breadth." 附带极简标注（local model runtime ↓, confidence ↑）。

**口播节选**：
> By the time the Value Mapper runs, the system may have lost track of early discoveries. Session memory preserves working context across steps. It's especially critical for local models with smaller context windows.

---

## 11. eval-design — Evaluation Design（2 steps · ~90s）

**信息池**：
- 3 文档：Earthworm genomics / biomedical study / bioremediation
- 多模型家族：GPT / Claude / Qwen
- N=10 重复
- Baselines: B1 (zero-shot), B2 (+RAG priors), B3 (+critic step), Full (FAIRiAgent)
- 两个 track：Track A (Metadata Schema → Hierarchical-F1), Track B (Value Extraction → row-aligned accuracy)

**开发计划**：
- step 1 — 简洁一览表（占画面 60%）：rows = baselines, columns = key features（planning, FAIR-DS lookup, critic, ISA assembly, rollback, memory）。每个 cell checkmark/cross。
- step 2 — 表下方展示两个 track 的 metric 定义：Hierarchical-F1 的定义公式 + Value accuracy 的定义。极简，大字体。

**口播节选**：
> Three scientific manuscripts, multiple model families, 10 repeats per pair. Four configurations from zero-shot to full agentic workflow. Two evaluation tracks: Schema and Values.

---

## 12. exp1 — Exp 1: Agentic Workflow vs Baselines（2 steps · ~90s）

**信息池**：
- B1→B2→B3→Full 的递增趋势
- Hierarchical-F1 提升最大 → 因为 baselines 不做 ISA row 重构
- Value accuracy 也有提升，但 gap 较小
- 可使用 `metadata_generation_f1_presentation.png` + `value_extraction_accuracy_presentation.png`

**开发计划**：
- step 1 — 柱状图 placeholder（或已有图）占画面 65%。4 组柱（B1/B2/B3/Full），2 种颜色（Hierarchical-F1 green + Value accuracy blue）。
- step 2 — 在图上叠加两个 annotation：在 Hierarchical-F1 的 Full 柱上方标注 "largest gain"；在 Full vs B3 之间标注 "ISA reconstruction matters"。

**口播节选**：
> The Full agentic design achieves the highest scores on both metrics. The improvement is largest on Hierarchical-F1 — the structural score. Getting the structure right is where the agentic design adds the most value.

---

## 13. deep-dive — Inside One Run: MAS vs Baseline（4 steps · ~180s）

**信息池**：
- 选一个代表性 run（specific document + model pair）
- FAIRiAgent trace：Planner → Knowledge Retriever → JSON Generator → Critic (RETRY) → Generator (repair) → Critic (ACCEPT) → Value Mapper
- Baseline 输出：wrong package, flat fields, hallucinated value, no ISA binding
- LLM 输出片段作为 evidence

**开发计划**：
- step 1 — 标题 "Inside One Run"。画面分为左右两栏：左 "FAIRiAgent Trace" 右 "Baseline Output"。
- step 2 — 左侧逐行展示 FAIRiAgent 的 6 个 step，每行显示一个 LLM 输出片段（等宽字体小框）。Planner 输出 → Knowledge Retriever 返回 → Generator 初始输出 → Critic 反馈 "missing mandatory field 'collection date'" → Generator 修复后输出 → Critic ACCEPT。
- step 3 — 右侧展示 baseline 的单次输出。用红色标注标注三个问题：① "Package not in FAIR-DS registry" ② "Fields flat — no ISA sheets" ③ "Value hallucinated"。
- step 4 — 底部总结："Agentic: 6 auditable steps, 1 repair → valid output" vs "Baseline: 1 step, invisible errors → unusable output"。

**口播节选**：
> On the left: the FAIRiAgent trace. Planner, Knowledge Retriever, Generator, Critic with RETRY, repair, ACCEPT. On the right: the baseline output — wrong package, flat fields, hallucinated value. The difference is not token count. It's auditability.

---

## 14. exp2-ablation — Exp 2: Ablation — Does Each Component Matter?（2 steps · ~90s）

**信息池**：
- Full → −Critic → −Rollback → −Memory
- −Critic: quality drops, hallucination rises
- −Rollback: further quality loss
- 每个组件都有独立贡献

**开发计划**：
- step 1 — Ablation bar chart placeholder 占画面 65%。横轴：Full / −Critic / −Rollback / −Memory。纵轴：Hierarchical-F1。叠加 hallucination rate 作为第二条线/色。
- step 2 — 两个 callout 标注：在 −Critic 柱上方 "Quality ↓, Hallucination ↑"；在 −Rollback 柱上方 "Some errors need re-grounding"。

**口播节选**：
> Remove the Critic: quality drops, hallucination rises sharply. Remove rollback: quality drops again. The critic is quality control, not decoration. Rollback is recovery, not redundancy.

---

## 15. exp3-passk — Exp 3: Pass@k — Reliability Through Repair（2 steps · ~75s）

**信息池**：
- Pass@k: probability of at least 1 successful run in k attempts
- 两条线：moderate threshold, strict threshold
- 曲线上升 → critic + retry 带来收敛，非 random sampling
- 对 curation 场景：稳定性 > 一次性运气

**开发计划**：
- step 1 — Pass@k 曲线图 placeholder 占画面 65%。x 轴 k=1..10，y 轴 success rate。两条线（不同颜色）：moderate 在上面，strict 在下面。两条都向上收敛。
- step 2 — 图上一句标注："Not random sampling — each attempt learns from Critic feedback."

**口播节选**：
> The curve rises as k increases. But this is not random sampling. Each attempt learns from the previous one through Critic feedback. For curation, one lucky first answer matters less than reliable convergence.

---

## 16. synthesis — Synthesis: Three Dimensions（2 steps · ~75s）

**信息池**：
- 三个维度：Reliability、Extraction Quality、Coverage
- 单一 metric 不够
- 可选使用 `figs/poster_fig3_fig4_combined.png`

**开发计划**：
- step 1 — 三维综合图 placeholder（或已有 combined 图）占画面主导。展示 reliability × quality × coverage 的关系。
- step 2 — 底部一句话："No single metric tells the full story."

**口播节选**：
> A system can be reliable but incomplete. It can extract correct values but miss required fields. No single metric is enough. The evaluation must preserve the distinction between Schema and Values.

---

## 17. takeaways — FAIRiAgent Makes FAIR Easy（3 steps · ~120s）

**信息池**：
- Theme ①：Metadata Schema 是 first-class task
- Theme ②：Values need their own evaluation
- Theme ③：Agent decomposition makes failure visible
- Theme ④：Source-grounded, not source-free
- 结论：These mechanisms make it clearer where to look, not remove the need for human review

**开发计划**：
- step 1 — 标题 "FAIRiAgent Makes FAIR Easy"。四个 theme 以 icon + 大字形式排列（2×2 网格）。
- step 2 — 逐行逐个 highlight，配 1-2 句解说文字（展开每个 theme）。
- step 3 — 底部总结："Not removing human review — making it clearer where to look."

**口播节选**：
> Four distilled themes. Schema is a first-class task. Values need their own evaluation. Agent decomposition makes failure visible. Source-grounded, not source-free. These mechanisms make it clearer where the system is strong and where it still needs work.

---

## 18. closing — Closing（1 step · ~45s）

**信息池**：
- 核心问题："Did the system reconstruct a metadata object that a curator can inspect?"
- Limitations 一句带过：FAIR-DS API dependency, value-level semantic evaluation, LLM backbone variance
- 联系方式

**开发计划**：
- step 1 — 核心问题大字居中占画面主体。底部 limitations 小字 + 联系方式。

**口播节选**：
> The central question is not "did the model find a value?" It's "did the system reconstruct a metadata object that a curator can inspect?" Thank you.
