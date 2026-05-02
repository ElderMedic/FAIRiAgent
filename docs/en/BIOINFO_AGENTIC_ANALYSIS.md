# 🧬 Bioinformatics Agentic Analysis

FAIRiAgent includes a specialized capability for **active metadata recovery** from raw biological data. This is particularly useful when descriptive documentation (like a research paper or README) is missing or sparse, but raw files like BAM or VCF are available.

## How it Works

When the `DocumentParserAgent` identifies raw biological files in the source workspace, it can invoke containerized bioinformatics tools to inspect them.

1. **Identification**: The agent detects files with extensions like `.bam`, `.vcf`, `.fastq`, etc.
2. **Tool Selection**: The agent selects an appropriate tool image from [quay.io/biocontainers](https://quay.io/organization/biocontainers).
3. **Execution**: The tool is run via Docker, mounting the local workspace to `/data` inside the container.
4. **Extraction**: The agent parses the tool's output (e.g., `samtools stats`) to recover metadata such as:
   - Read length
   - Paired-end status
   - Genome assembly (hg19 vs hg38)
   - Sample identifiers

## Prerequisites

- **Docker**: The host machine must have Docker installed and the daemon running.
- **Internet Access**: Required to pull Biocontainer images from `quay.io` (images are small and cached locally after the first run).

## Supported Tools (Examples)

The agent can theoretically use any tool from Biocontainers, but it is specifically guided for:
- **Samtools**: For BAM/SAM/CRAM stats and headers.
- **Bcftools**: For VCF/BCF header inspection and sample listing.

## Example Scenario: CompBioBench

In the [CompBioBench](https://github.com/Genentech/compbiobench-runner) dataset, many tasks provide only a BAM file and ask for the read length.

**Agent Task**: "For the given BAM file mt.sorted.bam, infer if it's paired or single ended reads and the read length."

**Agent Action**:
1. Locates `mt.sorted.bam`.
2. Calls `run_biocontainer_tool(image="quay.io/biocontainers/samtools:1.19.2--h50dae1a_1", command=["samtools", "stats", "/data/mt.sorted.bam"])`.
3. Analyzes the `SN` (Summary Numbers) section of the output.
4. Identifies `is paired: 1` and `average length: 57`.
5. Returns the metadata: `1x57`.

## Configuration

This feature is enabled by default in the `DocumentParserAgent`. It uses the `run_biocontainer_tool` defined in `fairifier/tools/bio_tools.py`.

The `bioinfo-analysis` skill (located in `fairifier/skills/domain/genomics/BIOINFO_ANALYSIS.md`) provides the LLM with the necessary "recipes" and strategy for using these tools.
