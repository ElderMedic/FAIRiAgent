# LLM-as-Judge Critic & Confidence 改造计划

> 参考近两年在 Agent-as-a-Judge、LLM-as-Judge（如 AutoGPT Eval Harness、AgentBench、LMM Judge）等研究中的通用范式：  
> 1) 由独立 LLM 以结构化 rubric 评分；2) 将客观度量（覆盖率、耗时、验证结果）与主观评分融合；3) 评分链路可追溯、可复算，并为下一次动作提供可操作反馈。

---

## 1. 改造目标

1. **Critic 重构**：以 LLM-as-Judge 模式编写 rubric，拆分成解析、检索、生成三个独立评分器，输出一致的 JSON schema，并消除硬编码阈值。  
2. **Confidence 统一**：以 Critic 的分数为主干，融合可计算指标（字段覆盖率、SHACL 结果、LLM 置信度分布）生成多维置信度，杜绝“加权拍脑袋”。  
3. **工作流治理**：合并双轨 LangGraph / Orchestrator，确保规划节点能改变后续执行（prompt、重试、跳步等），并删除不再使用的写死规则。  
4. **评估与验收**：提供自动化回归（至少 3 份样本文档 + Mock FAIR-DS 数据），输出 eval 报告以支撑验收。

---

## 2. 研究结论 & 设计基线

- **LLM-as-Judge Rubric**  
  - 每个节点至少包含：`accuracy`、`coverage`、`faithfulness`、`actionability` 四个维度；  
  - 评分输出统一为 `{"score": float(0~1), "decision": "accept|revise|escalate", "evidence": [], "improvement_ops": []}`；  
  - 结合 `chain-of-thought + verdict` Prompt，可附带 `critique` 字段供下一轮使用。

- **Confidence 融合模式（参考 Agent-as-a-Judge 论文）**  
  ```
  overall = w1 * critic_score + w2 * structural_metric + w3 * validation_metric
  ```
  - `structural_metric`: 字段覆盖率、evidence 覆盖率、平均字段置信度方差；  
  - `validation_metric`: SHACL 通过率、Schema 校验；  
  - 所有权重通过配置暴露，默认 `w1=0.5, w2=0.3, w3=0.2`，并记录每一项原始值供追溯。

- **工作流治理**  
  - 参考 AutoGen / LangGraph 官方推荐：只有一条状态机，规划节点产出的 `plan` 将写入 `state["guidance"]` 并驱动后续 prompt（例如决定检索需关注的 package 范围、生成节点的字段预算）；  
  - 取消未被调用的 fallback 代码，若需保留“离线模式”则通过 `config.use_llm` 显式切换并添加测试。

---

## 3. 实施路线

### 阶段 A：基础梳理（1~2 天）
1. **统一工作流**  
   - 选择 LangGraph node-based 版本为唯一入口；  
   - 删除 `fairifier/graph/workflow.py` 与 `OrchestratorAgent`，保留其中有价值的 ReAct 逻辑并迁移；  
   - 明确 `execution_plan` 的使用点，定义 `plan -> context` 映射表。
2. **清理死代码**  
   - 移除 DocumentParser/KnowledgeRetriever/JSONGenerator 中未被调用的正则/关键字路径；  
   - 删除 `_group_fields_by_isa_level_OLD_DEPRECATED` 等遗留方法；  
   - 若未来需要 fallback，通过单元测试验证后再引入。

### 阶段 B：Critic 重构（3~4 天）
1. **Rubric 定义**  
   - 在 `docs/` 下新增 rubric（YAML/JSON），描述各节点维度与示例；  
   - Prompt 模板引用 rubric，确保输出 schema 一致。  
2. **执行流程**  
   - `critic.py` 仅负责 orchestrate：构建输入上下文、调用 LLM、解析结构化 JSON；  
   - `provide_feedback_to_agent` 改为输出 `improvement_ops`，各 Agent 在 prompt 中显式消费；  
   - 失败/超时策略：默认 `decision = "escalate"` 并中断，避免 silent accept。

### 阶段 C：Confidence 管线（2~3 天）
1. **指标采集**  
   - 在各 Agent 中记录：字段数量、evidence 覆盖、字段置信度分布、SHACL 结果；  
   - 将这些数据写入 `state["quality_metrics"]`，供统一模块使用。  
2. **融合逻辑**  
   - 新增 `fairifier/services/confidence_aggregator.py`（或 utils）；  
   - 计算 `overall_score`、`dimension_breakdown`，并写入输出 JSON + CLI/UI；  
   - 提供可配置权重与阈值，低于阈值自动标记 `needs_human_review`.

### 阶段 D：验证与文档（2 天）
1. **Eval Flow**  
   - 增补 `quick_test.sh` 或 `tests/`，针对三份样例跑流程并保存 Critic 结果；  
   - 生成 `output/*/evaluation.json`，记录评分、置信度、关键决策。  
2. **文档 & 升级指南**  
   - 更新 `docs/development/WORKFLOW_SUMMARY.md` & `PROJECT_SUMMARY.md` 中的相关章节；  
   - 撰写迁移指南，说明配置、指标含义、如何解读 Critic 报告。

---

## 4. 交付物 & 验收

| 交付物 | 内容 | 验收方式 |
| --- | --- | --- |
| `docs/development/critic_rubric.yaml` | 三个节点的 rubric、评分 schema | 走查 + prompt 测试 |
| 新版 `critic.py` | LLM-as-Judge 实现、错误处理、反馈结构 | 代码评审 + 单测覆盖 |
| `confidence_aggregator` | 多维置信度 + 可配置权重 | 运行样例文档，输出分布 |
| Eval 报告 | 每个样例的评分与 SHACL 结果 | 关键指标对比旧版 |

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| LLM 评分不稳定 | 重复执行差异大 | 使用温度 0 + rubric + self-consistency（多次评分取平均） |
| Eval 成本上升 | 运行时间 / token 消耗增加 | 通过 caching + 可选“快速模式” |
| 旧版本依赖（UI/CLI） | 兼容性破坏 | 在 CLI 参数中保留 `--legacy-critic` 切换，待验证后移除 |

---

## 6. 下一步

1. 与业务方确认 rubric 维度与权重；  
2. 评估是否需要引入外部评测框架（如 DeepEval）的现成实现；  
3. 完成本计划审阅后，再启动具体代码改造。

