# FAIRiAgent Seminar — Bilingual Speaker Script

**SSB Seminar 2026 · May 12, 2026 · Helix**
**Changlin Ke · Systems & Synthetic Biology, Wageningen U&R**

---

## Slide 1 — Title

**EN:** FAIRiAgent: Reconstructing FAIR Metadata Objects with Multi-Agent Workflows. I'm going to talk about a problem that anyone who's ever tried to submit data to a public repository has felt: FAIR metadata is hard. And I'll show you how we're using agentic workflows to make it easier.

**ZH:** FAIRiAgent：用多智能体工作流重建 FAIR 元数据对象。我要讲的是一个所有尝试过提交公共数据库的人都感受过的问题：FAIR 元数据很难。我会展示我们如何用 agentic 工作流让它变得更简单。

---

## Slide 2 — FAIR by Design — But Difficult in Practice

**EN:** Let's start with the reality that experimental biologists face. FAIR principles tell us data should be Findable, Accessible, Interoperable, and Reusable. But actually producing FAIR-compliant metadata? That's a different story.

**ZH:** 让我们从实验生物学家面对的现实开始。FAIR 原则告诉我们数据应该是可查找、可获取、可互操作、可复用的。但真正产出符合 FAIR 标准的元数据？那是另一回事。

---

**EN:** Think about what a researcher has to do. Plan what metadata to collect, ideally before the experiment. Fill values across multiple ISA layers. Learn community standards. All while the paper deadline approaches. FAIR-DS provides the standard packages and fields, but the tool has a learning curve. You still have to manually fill values.

**ZH:** 想想一个研究者要做什么。规划要收集什么元数据，最好在实验之前。在多层 ISA 结构中填写值。学习社区标准。所有这些都发生在论文截止日期逼近的时候。FAIR-DS 提供了标准包和字段，但这个工具有学习曲线，你还是得手动填值。

---

**EN:** So the question becomes: how can we make this easier?

**ZH:** 所以问题变成了：我们怎么让它更简单？

---

## Slide 3 — The Target: A 5-Layer ISA Metadata Object

**EN:** To understand why this is hard, you need to see what we're actually asking people to produce. FAIR metadata is not a flat table. It's a 5-layer hierarchical object following the ISA model.

**ZH:** 要理解为什么这么难，你需要看到我们到底在要求人们产出什么。FAIR 元数据不是一个平面的表格，而是一个遵循 ISA 模型的 5 层层次化对象。

---

**EN:** At the top, Investigation captures project-level context. Study defines the research design. Then three multi-row layers: Observation Unit, Sample, and Assay. Each can have multiple rows, and fields within the same layer must be bound to the correct row. This is not a form-filling problem. This is structured object reconstruction.

**ZH:** 最上层是 Investigation，捕捉项目级别的上下文。Study 定义研究设计。然后是三个多行层级：Observation Unit、Sample 和 Assay。每个都可以有多行，同一层内的字段必须绑定到正确的行。这不是填表问题，这是结构化对象重建。

---

## Slide 4 — "Outsource the Boring Work" — Can LLMs Help?

**EN:** So here's a natural thought: LLMs can read papers and extract information. Why not outsource the boring metadata work to an LLM?

**ZH:** 一个自然的想法：LLM 可以读论文、提取信息。为什么不把无聊的元数据工作外包给 LLM 呢？

---

**EN:** But there's a fundamental difference between asking an LLM to generate text, and asking it to reconstruct a structured metadata object that obeys a specific schema with row-level binding. This is the paradigm shift: from a single prompt-response to a multi-step auditable workflow.

**ZH:** 但让 LLM 生成文本，和让它重建一个遵循特定 schema、需要行级绑定的结构化元数据对象，有本质区别。这就是范式转变：从单次 prompt-response 到多步可审计的工作流。

---

## Slide 5 — Why Raw LLM Falls Short

**EN:** Here's what happens when you ask a single LLM call to produce FAIR metadata.

**ZH:** 这是当你用单次 LLM 调用生成 FAIR 元数据时实际发生的情况。

---

**EN:** First: hallucination. The model invents package names that don't exist. It makes up accession numbers. Let me show you an example. "BioSeqPipeline v3.1" — sounds technical, doesn't exist in any registry.

**ZH:** 第一：幻觉。模型编造不存在的包名。伪造 accession number。给你们看个例子。"BioSeqPipeline v3.1"——听着很技术，但在任何标准库里都不存在。

---

**EN:** Second: context rot. In a long document, the model forgets early information. By the time it's generating assay-level fields, it's already lost the sampling context from the methods section.

**ZH:** 第二：上下文腐烂。在长文档中，模型会忘记早期的信息。当它在生成 assay 级别的字段时，已经丢失了方法部分中的采样上下文。

---

**EN:** Third: no ISA structure. The output is flat. Fields without sheet assignment, without row binding, without entity grouping. It looks like metadata, but it's not usable for submission.

**ZH:** 第三：没有 ISA 结构。输出是扁平的。字段没有 sheet 分配、没有行绑定、没有实体分组。看起来像元数据，但无法用于提交。

---

## Slide 6 — Two Tasks That Fail Differently

**EN:** This is where the core insight comes in. Metadata generation is actually two distinct tasks, and they fail differently.

**ZH:** 这就是核心洞察所在。元数据生成实际上是两个不同的任务，它们的失败方式也不同。

---

**EN:** Metadata Schema is about structure: which package, which fields, which ISA sheet, which row. Value Extraction is about content: what value, which row, what evidence.

**ZH:** Metadata Schema 是关于结构：选哪个包、生成哪些字段、分配到哪个 ISA sheet、属于哪一行。Value Extraction 是关于内容：填什么值、属于哪一行、有什么证据。

---

**EN:** A system can select the correct package but fill incorrect values. And a system can extract plausible values while failing to reconstruct the ISA hierarchy. These two tasks must be designed and evaluated separately.

**ZH:** 一个系统可以选对包但填错值。另一个可以提取看似合理的值但完全无法重建 ISA 层级。这两个任务必须分开设计、分开评估。

---

## Slide 7 — Decomposing into Agent Roles

**EN:** So here's our approach. Instead of one massive prompt, we decompose the problem into a set of agent roles. Each agent addresses a specific failure mode. The point is not more LLM calls. It's that each call has an auditable responsibility.

**ZH:** 所以这是我们的方案。不是一个巨大的 prompt，而是把问题分解为一组 agent 角色。每个 agent 解决一种特定的失败模式。关键不是更多的 LLM 调用，而是每次调用都有一个可审计的职责。

> *Speaker walks through the architecture figure. Point out: Document Parser → Planner → Knowledge Retriever (FAIR-DS grounding) → JSON Generator → Value Mapper, each followed by Critic gate.*

---

## Slide 8 — Grounding in Community Standards

**EN:** Let me zoom in on grounding, one of the most important pieces. Without grounding, the LLM generates field names from training data — some real, some hallucinated. No way to tell which is which.

**ZH:** 让我聚焦在 grounding 上，这是最重要的部分之一。没有 grounding，LLM 从训练数据中生成字段名——有些是真的，有些是编的。没办法区分。

---

**EN:** With FAIR-DS grounding, the agent queries the live terminology service. It asks: what packages exist? What fields does this package require? Then it generates metadata constrained by what actually exists.

**ZH:** 有了 FAIR-DS grounding，agent 会查询实时术语服务。它会问：有哪些包？这个包需要哪些字段？然后它生成的元数据受限于实际存在的内容。

---

**EN:** Here's a concrete example. Without grounding: the LLM invents "BioSeqPipeline v3.1" — sounds plausible, doesn't exist. With grounding: the system correctly selects "Genome" from the FAIR-DS registry. The difference is not model size. It's access to authoritative sources.

**ZH:** 举一个具体例子。没有 grounding：LLM 编造了 "BioSeqPipeline v3.1"——听着挺专业，实际不存在。有 grounding：系统正确地从 FAIR-DS 注册表中选了 "Genome"。这个差别不是模型大小，而是能否获取权威数据源。

---

## Slide 9 — Self-Correction: Critic + Rollback

**EN:** Even with grounding, agents make mistakes. So we add a self-correction mechanism. After each agent, a Critic evaluates the output against a rubric: schema compliance, data types, confidence thresholds.

**ZH:** 即使有 grounding，agent 也会犯错。所以我们加了自校正机制。每个 agent 之后，Critic 会根据评分标准评估输出：schema 合规性、数据类型、置信度阈值。

---

**EN:** The decision is three-way. Accept and move on. Retry with specific feedback. Escalate for human review. But here's the key: some errors can't be fixed by just trying again. The system sometimes needs rollback to an earlier state.

**ZH:** 决策有三条路径。Accept 继续前进。Retry 带具体反馈重试。Escalate 标记为人工审核。但关键是：有些错误不是再试一次能修复的。系统有时候需要回滚到更早的状态。

---

**EN:** That's the difference between "try harder" and "try differently." Rollback re-queries the API, re-reads the document, regenerates from a better starting point.

**ZH:** 这就是"更努力地试"和"换个方式试"的区别。Rollback 重新查询 API、重新读文档、从更好的起点重新生成。

---

## Slide 10 — Session Memory

**EN:** One more challenge: context degradation. By the time the Value Mapper runs, the system may have lost track of early discoveries. Session memory preserves working context across steps.

**ZH:** 还有一个挑战：上下文退化。当 Value Mapper 运行时，系统可能已经丢失了早期发现的信息。Session memory 在步骤之间保留工作上下文。

---

**EN:** In our experiments, memory reduces runtime for local models and improves or maintains metadata breadth. It's especially critical for smaller context windows.

**ZH:** 在我们的实验中，memory 减少了本地模型的运行时间，提升或保持了元数据的广度。对于较小的上下文窗口尤其关键。

---

## Slide 11 — Evaluation Design

**EN:** Now let me show you the evidence. We evaluated on three scientific manuscripts, multiple model families from GPT, Claude, and Qwen. Ten repeats per document-model pair to quantify variance.

**ZH:** 现在让我展示实验结果。我们在三篇科学手稿上做了评估，使用了多个模型家族——GPT、Claude、Qwen。每个文档-模型对重复 10 次以量化方差。

---

**EN:** Four configurations: B1 zero-shot, B2 with RAG priors, B3 with a critic step, and the Full FAIRiAgent workflow. Two evaluation tracks: Metadata Schema using Hierarchical-F1, and Value Extraction using row-aligned accuracy.

**ZH:** 四种配置：B1 零样本、B2 带 RAG 先验知识、B3 带 critic 步骤、以及完整的 FAIRiAgent 工作流。两个评估轨道：Metadata Schema 用 Hierarchical-F1 来衡量，Value Extraction 用行对齐的准确率来衡量。

---

## Slide 12 — Exp 1: Agentic Workflow vs Baselines

**EN:** The first question: does the agentic workflow improve extraction? The answer is yes. Across all baselines, Full achieves the highest scores on both metrics.

**ZH:** 第一个问题：agentic 工作流是否改进了提取？答案是肯定的。在所有基线中，完整 FAIRiAgent 在两个指标上都取得了最高分。

---

**EN:** But look at the gap. The improvement is largest on Hierarchical-F1, the structural score. Baselines don't do ISA row reconstruction. Value accuracy also improves, but the gap is smaller. Getting the structure right is where the agentic design adds the most value.

**ZH:** 但请看差距。提升最大的是 Hierarchical-F1，也就是结构得分。基线不做 ISA 行重建。Value accuracy 也有提升，但差距更小。把结构做对，是 agentic 设计最增值的地方。

---

## Slide 13 — Inside One Run: MAS vs Baseline

**EN:** Let me take you inside one concrete run to show what's actually happening.

**ZH:** 让我带你们看一个具体的运行，展示实际发生了什么。

---

**EN:** On the left: the FAIRiAgent trace. The Planner identifies the domain and prioritizes the Genome package. The Knowledge Retriever queries FAIR-DS and returns real field definitions.

**ZH:** 左侧是 FAIRiAgent 的 trace。Planner 识别领域并优先选择 Genome 包。Knowledge Retriever 查询 FAIR-DS 并返回真实的字段定义。

---

**EN:** The Generator produces fields with ISA sheet assignments. The Critic evaluates, finds a missing mandatory field, returns RETRY with specific feedback. The Generator retries, adds the field with evidence, and the Critic accepts.

**ZH:** Generator 生成带 ISA sheet 分配的字段。Critic 评估，发现缺失必填字段，返回 RETRY 并给出具体反馈。Generator 重试，加上带证据的字段，Critic accept。

---

**EN:** [Show figure] On the right: the baseline output from a single prompt. Wrong package, flat fields, hallucinated accession number, no ISA row binding. The difference is not token count. It's auditability.

**ZH:** [展示图] 右侧是单次 prompt 的 baseline 输出。错误的包、扁平字段、编造的 accession number、没有 ISA 行绑定。区别不在于用了多少 token，而在于可审计性。

---

## Slide 14 — Exp 2: Ablation — Does Each Component Matter?

**EN:** Do you really need all these pieces? We tested by systematically removing components.

**ZH:** 真的需要所有这些组件吗？我们通过系统性地移除组件来测试。

---

**EN:** Remove the Critic: quality drops, hallucination rises sharply. Remove rollback: quality drops again. Each component matters. The critic is quality control, not decoration.

**ZH:** 移除 Critic：质量下降、幻觉显著上升。移除 Rollback：质量进一步下降。每个组件都有用。Critic 是质量控制，不是装饰品。

---

## Slide 15 — Exp 3: Pass@k — Reliability Through Repair

**EN:** The third experiment asks: if you give the system multiple attempts, how often does it succeed? This is Pass@k.

**ZH:** 第三个实验问的是：如果给系统多次尝试，它成功的概率是多少？这就是 Pass@k。

---

**EN:** The more attempts, the higher the probability of producing a valid metadata object.

**ZH:** 尝试次数越多，产出一个有效元数据对象的概率越高。

---

## Slide 16 — What FAIRiAgent Teaches Us About Curation

**EN:** So what do we learn from FAIRiAgent beyond the implementation itself?

**ZH:** 那么，除了系统实现本身，FAIRiAgent 给我们的启示是什么？

---

**EN:** The first point is that FAIR metadata management is not only value extraction. The target is a structured description of the study: design, samples, assays, values, and evidence. That is why the system has to reason over the metadata object, not just produce a summary of the paper.

**ZH:** 第一，FAIR metadata management 不只是 value extraction。目标是对一个研究进行结构化描述：实验设计、样本、assay、数值和证据。所以系统需要围绕 metadata object 推理，而不是简单总结论文。

---

**EN:** The second point is that community standards need to guide the workflow itself. FAIR-DS packages and fields are not something to clean up after generation. They should constrain what the agent proposes. And the third point is evidence: a curator needs to see where a value came from, which ISA row it belongs to, and what remains uncertain.

**ZH:** 第二，community standards 需要直接指导工作流。FAIR-DS 的 packages 和 fields 不是生成之后再清理的东西，而应该约束 agent 能提出什么。第三是 evidence：curator 需要看到每个值来自哪里、属于哪一行 ISA row、还有哪些地方不确定。

---

**EN:** The broader goal is assisted curation, not full automation. The agent reduces repetitive searching and form filling, but the scientist still controls interpretation, correction, and final release.

**ZH:** 更大的目标是 assisted curation，而不是 full automation。Agent 减少重复搜索和填表，但科学家仍然负责解释、修正和最终发布 metadata。

---

## Slide 17 — Closing

**EN:** The central question is not: did the model find a value? FAIRiAgent does not replace scientific expertise. It **Scales** it. Thank you.

**ZH:** 核心问题不是：模型找到了一个值吗？FAIRiAgent 不是替代科学专业知识，而是**放大**它。谢谢。

---

*End of script · 17 slides · ~25–30 min*
