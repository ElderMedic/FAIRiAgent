---
name: bioinfo-analysis
description: Guidance for using bioinformatics tools (samtools, bcftools, etc.) via biocontainers to infer metadata.
when_to_use: Use when you have raw biological data (BAM, VCF, FASTQ) and need to recover missing metadata like read length, paired-end status, or organism.
---

# Bioinformatics Data Analysis Guidance

When missing narrative metadata, use the tools below to inspect raw data.

## Available Tools

### search_biocontainer_tags
**USE THIS FIRST** before any container pull. Query the quay.io/biocontainers registry to verify available image tags. Args:
- `tool_name`: Short tool name, e.g. `"samtools"`, `"bcftools"`, `"fastqc"`
Returns the latest active tags with digests and sizes. If the default image fails to pull, use this to discover alternative tags.

### run_biocontainer_tool
Run a bioinformatics tool inside a Docker container. Args:
- `image`: Full quay.io image path (prefer verified tags from search_biocontainer_tags) or short alias `"samtools"` / `"bcftools"`
- `command`: List of command + arguments, e.g. `["samtools", "stats", "/data/file.bam"]`
- `host_path`: ABSOLUTE host path to the data file on disk

The tool mounts `dirname(host_path)` into the container at `/data`, so reference files as `/data/<filename>`.

### decompress_gzip_tool
Decompress `.gz` files in-place. Takes `host_path` (absolute path), returns path to decompressed file.

### extract_archive_tool
Extract `.tar` or `.tar.gz` archives to a temp directory. Returns list of extracted files.

## Common Recipes

### Inspecting BAM files (samtools)
- **First:** call `search_biocontainer_tags("samtools")` to verify the latest tag exists
- Image: use the verified tag from search, or fallback alias `"samtools"`
- Command: `["samtools", "stats", "/data/mt.sorted.bam"]`
- host_path: the absolute path from bio_file_paths
- Goal: Find "is paired:", "average length:", "insert size average:", reference name.

### Inspecting VCF files (bcftools)
- **First:** call `search_biocontainer_tags("bcftools")` to verify the latest tag exists
- Decompress with `decompress_gzip_tool` if `.vcf.gz`
- Image: use the verified tag from search, or fallback alias `"bcftools"`
- Command: `["bcftools", "view", "-H", "/data/file.vcf"]`
- Goal: Check chromosome names (hg19 vs hg38) and sample names.

### Inspecting FASTQ files
- **First:** call `search_biocontainer_tags("fastqc")` to verify the latest tag exists
- Decompress with `decompress_gzip_tool` if `.fq.gz` / `.fastq.gz`
- Image: `quay.io/biocontainers/fastqc:<verified_tag>`
- Command: `["fastqc", "--extract", "/data/file.fastq"]`
- Or read headers directly from decompressed file for read length, paired info.

## Strategy
1. Your `bio_file_paths` tells you where the data files are on disk.
2. Identify file types by extension. For `.gz` files, decompress first if the tool expects uncompressed input.
3. **CRITICAL: Before running any Docker container, call `search_biocontainer_tags(tool_name)` to verify the image exists on quay.io.** If the first tag fails to pull, try another tag from the search results.
4. For `.bam` → samtools. For `.vcf` → bcftools. For `.fastq` → head/fastqc.
5. Parse the tool output and extract metadata fields to complement document_info.
6. Return structured metadata via the standard response format.
