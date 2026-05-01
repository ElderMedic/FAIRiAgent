# Source Workspace 与多文件输入

FAIRiAgent 现在把输入文件保存在 source workspace 中，而不是把 context
限制当成可以丢弃信息的理由。Prompt 里只放紧凑的 source inventory 和 evidence
片段；完整原文和表格行保留在每次 run 的输出目录里。

## 产物

当 `FAIRIFIER_SOURCE_WORKSPACE_ENABLED=true` 时，每次 run 会写出：

- `source_workspace/source_manifest.json`：source id、路径、读取方法、角色、大小和表格引用。
- `source_workspace/source_workspace.md`：给 agent 和报告使用的紧凑 inventory。
- `source_workspace/sources/source_*.md`：完整 source 文本或 MinerU markdown。
- `source_workspace/tables/*.jsonl`：CSV/TSV/Excel 的完整表格行。

单文件 run 也走同一结构，只是只有一个 source。目录和 zip 输入会为每个支持的文件创建 source。

## 多文件稳定性

在应用文件数量上限之前，系统会优先选择更像 research source 的文件：main
manuscript、supplement、metadata/sample 文件、表格、protocol/method 文件。普通
notes、administrative 文件会被降权，避免它们抢占有限的输入名额。

当前合并路径仍然会在逐 source parsing 后记录 field conflict。Source workspace 是后续做更严格
field-level source weighting 和 outlier handling 的基础。

## Metadata Evidence Search

JSON metadata generation 阶段会基于保留下来的 workspace 构建 field-specific evidence
context。对每个 FAIR-DS field，系统会用 field name 和 description 生成字面量查询，
搜索 source text。对表格输入，系统会搜索完整 JSONL 表格行的列名和单元格值，所以即使
value 不在 table preview 里，也可以被送入 LLM 的字段上下文。

找到 evidence 时，prompt 会要求模型在 metadata evidence 字段里优先引用
`source_001:123-145` 或 `source_002 table samples row 4` 这类 source reference。

生成后，系统会检查高置信度 metadata field 是否包含这类 source reference。如果字段高于
`FAIRIFIER_METADATA_SOURCE_REF_MIN_CONFIDENCE` 但没有 source reference，FAIRiAgent
会把它降到 `FAIRIFIER_METADATA_SOURCE_REF_DOWNGRADE_CONFIDENCE`，并保持 provisional。

## 配置

可以通过 `.env` 或 shell 环境变量配置：

```bash
FAIRIFIER_SOURCE_WORKSPACE_ENABLED=true
FAIRIFIER_SOURCE_WORKSPACE_DIR_NAME=source_workspace
FAIRIFIER_SOURCE_MAX_SELECTED_INPUTS=8
FAIRIFIER_SOURCE_INVENTORY_MAX_CHARS_PER_SOURCE=4000
FAIRIFIER_SOURCE_READ_MAX_CHARS=8000
FAIRIFIER_SOURCE_GREP_CONTEXT_CHARS=600
FAIRIFIER_SOURCE_MAX_SEARCH_RESULTS=20
FAIRIFIER_SOURCE_ROLE_DETECTION_ENABLED=true
FAIRIFIER_SOURCE_MIN_RELEVANCE_SCORE=0.35
FAIRIFIER_SOURCE_OUTLIER_POLICY=downweight
FAIRIFIER_METADATA_CONTEXT_MODE=agentic_search
FAIRIFIER_METADATA_MAX_CONTEXT_CHARS_PER_FIELD=12000
FAIRIFIER_METADATA_SOURCE_REF_MIN_CONFIDENCE=0.75
FAIRIFIER_METADATA_SOURCE_REF_DOWNGRADE_CONFIDENCE=0.6
FAIRIFIER_TABLE_FULL_SCAN_ENABLED=true
FAIRIFIER_TABLE_SEARCH_MAX_ROWS=5000
FAIRIFIER_TABLE_SEARCH_MAX_MATCHES=50
```

这些 `*_MAX_CONTEXT_*`、grep、table-search 参数只限制单次暴露给 agent 的材料量，
不会从 workspace 中删除原始内容。
