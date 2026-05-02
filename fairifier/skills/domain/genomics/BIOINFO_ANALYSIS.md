---
name: bioinfo-analysis
description: Guidance for using bioinformatics tools (samtools, bcftools, etc.) via biocontainers to infer metadata.
when_to_use: Use when you have raw biological data (BAM, VCF, FASTQ) and need to recover missing metadata like read length, paired-end status, or organism.
---

# Bioinformatics Data Analysis Guidance

When missing narrative metadata, use the tools below to inspect raw data.

## Available Tools

### run_biocontainer_tool
Run a bioinformatics tool inside a Docker container. Args:
- `image`: Docker image name (auto-pulled if missing)
- `command`: List of command + arguments, e.g. `["samtools", "stats", "/data/file.bam"]`
- `host_path`: ABSOLUTE host path to the data file on disk

The tool mounts `dirname(host_path)` into the container at `/data`, so reference files as `/data/<filename>`.

### decompress_gzip_tool
Decompress `.gz` files in-place. Takes `host_path` (absolute path), returns path to decompressed file.

### extract_archive_tool
Extract `.tar` or `.tar.gz` archives to a temp directory. Returns list of extracted files.

## Common Recipes

### Inspecting BAM files (samtools)
- Image: `quay.io/biocontainers/samtools:1.19.2--h50dae1a_1`
- Command: `["samtools", "stats", "/data/mt.sorted.bam"]`
- host_path: the absolute path, e.g. `/home/.../mt.sorted.bam`
- Goal: Find "is paired:", "average length:", "insert size average:", reference name.

### Inspecting VCF files (bcftools)
- First decompress with `decompress_gzip_tool` if `.vcf.gz`
- Image: `quay.io/biocontainers/bcftools:1.19--h8b25389_1`
- Command: `["bcftools", "view", "-H", "/data/file.vcf"]`
- Goal: Check chromosome names (hg19 vs hg38) and sample names.

### Inspecting FASTQ files
- First decompress with `decompress_gzip_tool` if `.fq.gz` / `.fastq.gz`
- Image: `quay.io/biocontainers/fastqc:0.12.1--hdfd78af_0`
- Command: `["fastqc", "--extract", "/data/file.fastq"]`
- Or read headers directly from decompressed file for read length, paired info.

## Strategy
1. Your `bio_file_paths` tells you where the data files are on disk.
2. Identify file types by extension. For `.gz` files, decompress first if the tool expects uncompressed input.
3. For `.bam` → samtools. For `.vcf` → bcftools. For `.fastq` → head/fastqc.
4. Parse the tool output and extract metadata fields to complement document_info.
5. Return structured metadata via the standard response format.
