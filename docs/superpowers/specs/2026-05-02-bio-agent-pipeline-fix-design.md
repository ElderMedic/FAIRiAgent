# Bio Agent Pipeline Fix — Design Spec

2026-05-02 | Status: approved

## Problem

FAIRiAgent cannot extract metadata from biological data files (BAM, VCF, FASTQ, h5ad) because:
1. Binary files get a placeholder string fed to DocumentParser — LLM hallucinates from filename
2. `run_biocontainer_tool` mounts `pwd` instead of the data file's directory — Docker can't find files
3. Gzip-compressed text files (.tsv.gz, .bed.gz) are treated as binary instead of decompressed
4. Mem0 memory service fails with 404 (Qdrant client/server version mismatch)

## Architecture

### File Classification & Routing

The orchestrator classifies every input file into four categories:

| Category    | Extensions                                          | Route                                        |
|-------------|-----------------------------------------------------|----------------------------------------------|
| BIO_BINARY  | .bam, .vcf, .vcf.gz, .fq, .fastq, .fq.gz, .fastq.gz, .h5ad | DocParser on companion docs → BioMetadataAgent with host paths |
| GZIPPED_TEXT| .tsv.gz, .bed.gz, .tagalign.gz, .csv.gz, .txt.gz   | Decompress → DocParser (normal pipeline)     |
| ARCHIVE     | .tar.gz, .tar                                       | Extract → classify each entry recursively   |
| TEXT        | .pdf, .txt, .md, .csv, .tsv, .bed, .tfam, .json    | DocumentParser (current pipeline, unchanged) |

### BioMetadataAgent Context

State gains `bio_file_paths: List[str]` — absolute host paths for all BIO_BINARY files.
BioMetadataAgent receives:
- Parsed `document_info` + `evidence_packets` from companion docs
- `bio_file_paths` for tool access
- bioinfo-analysis skill loaded as seed file

### Tool Rewrite — run_biocontainer_tool

```
run_biocontainer_tool(
    image: str,        # "quay.io/biocontainers/samtools:1.19.2--h50dae1a_1"
    command: List[str],# ["samtools", "stats", "/data/file.bam"]
    host_path: str,    # "/home/.../data/file.bam" — absolute host path
)
```

Mounts `dirname(host_path)` → `/data` in container. Auto-pulls image if missing.
Docker command: `docker run --rm -v <parent_dir>:/data -w /data <image> <command>`

### New Tools

- `decompress_gzip_tool(host_path)` — gunzip to same dir, return decompressed path
- `extract_archive_tool(host_path)` — extract tar/tar.gz to temp dir, return file list

### Mem0 Fix

- Qdrant server: v1.7.0 → v1.13.0 (container replaced)
- qdrant-client: 1.17.1 → 1.13.3 (pip downgrade)
- Embedding model default: `nomic-embed-text` → `nomic-embed-text-v2-moe:latest`
- Add health check at init + graceful degradation when unavailable

## Implementation Order

| Priority | Change                                               |
|----------|------------------------------------------------------|
| P0       | run_biocontainer_tool rewrite (host_path + auto-pull)|
| P0       | decompress_gzip_tool + extract_archive_tool           |
| P0       | Orchestrator file classification & routing            |
| P1       | BioMetadataAgent context enhancement                  |
| P1       | Mem0 health check + graceful degradation              |
| P2       | Ground truth dataset rewrite                          |
