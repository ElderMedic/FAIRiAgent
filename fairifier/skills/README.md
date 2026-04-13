# Agent skills (Anthropic-style `SKILL.md`)

Inner-loop agents (**DocumentParser**, **KnowledgeRetriever**) load skills into a virtual workspace:

- **`/workspace/skills_catalog.md`** — YAML frontmatter summary (`name`, `description`, `when_to_use`) for every skill entrypoint.
- **`/skills/...`** — Full markdown bodies: each `SKILL.md` plus other `*.md` in the same skill folder (see `fairifier/skills/__init__.py` for caps and nested-skill rules).

Requires **`FAIRIFIER_ENABLE_DEEP_AGENTS`** (default on) and the `deepagents` dependency.

## Built-in examples (good for demos)

These ship under `fairifier/skills/domain/` and appear in the virtual tree as below.

| Virtual path | `name` (frontmatter) | When it tends to apply |
|--------------|----------------------|-------------------------|
| `/skills/domain/genomics/SKILL.md` | `genomics-metadata` | Sequencing, genomes, transcriptomics, metagenomics, assemblies, accessions |
| `/skills/domain/plant_pathology/SKILL.md` | `plant-pathology-metadata` | Crops, pathogens, inoculation, plant disease, phenotyping |
| `/skills/domain/bioremediation/SKILL.md` | `bioremediation-metadata` | Remediation, pollutants, contaminated sites, soil treatment, microbial cleanup |

**Demo talking points**

1. Open the repo file `fairifier/skills/domain/genomics/SKILL.md` — show YAML frontmatter + body checklist.
2. Explain that at runtime the model sees the same content at **`/skills/domain/genomics/SKILL.md`** and a one-screen index in **`/workspace/skills_catalog.md`**.
3. Optional: add a sibling file `fairifier/skills/user/demo_skill/NOTES.md` — only if you want to show multi-file skills (not required for a minimal demo).

## User-defined skills (merge, do not fork builtins)

- **Repo-local**: add folders with `SKILL.md` under `fairifier/skills/` (e.g. `fairifier/skills/user/<your-skill>/SKILL.md`).
- **External trees**: set env vars (see `env.example`):
  - `FAIRIFIER_SKILLS_EXTRA_DIRS` — extra roots, OS path separator (`:` on Unix); **later path wins** on same relative path.
  - `CLAUDE_SKILLS_PATH` — same semantics, for tooling compatibility.
  - `FAIRIFIER_IMPORT_CLAUDE_SKILLS=true` — also load `~/.claude/skills` and `<repo>/.claude/skills` when present.
  - `FAIRIFIER_SKILLS_DIR` — replaces the **default** builtin root only; usually keep default and use `EXTRA_DIRS` for add-ons.

## Minimal skill template (copy-paste)

```markdown
---
name: my-lab-metadata
description: Short line about what this skill does and what metadata it improves.
when_to_use: Use when documents mention X, Y, or Z (be specific).
---

# My lab — metadata playbook

- Bullet checklist the inner agent should follow.
- Prefer FAIR-DS-friendly terminology; avoid inventing package names.
```

## Verify loading (optional)

From the repo root, with `FAIRiAgent` env active:

```bash
python -c "from fairifier.config import config; from fairifier.skills import list_skill_virtual_paths, build_skills_catalog_markdown; \
print('\n'.join(list_skill_virtual_paths(*config.skill_roots))); \
print('---'); print(build_skills_catalog_markdown(*config.skill_roots)[:1200])"
```

You should see the three `domain/.../SKILL.md` paths and a catalog containing their frontmatter.
