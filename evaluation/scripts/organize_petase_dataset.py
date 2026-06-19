#!/usr/bin/env python3
"""
Organize PETase papers dataset into the evaluation framework.

Copies PDFs and ground truth JSONs from the flat PETase_papers_json directory
into the standard evaluation/datasets/raw/ and evaluation/datasets/annotated/
structure WITHOUT modifying any original data.

Usage:
    python evaluation/scripts/organize_petase_dataset.py
"""

import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "PETase_papers_json"
RAW_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "raw" / "petase_enzyme_engineering"
PAPERS_DIR = RAW_DIR / "papers"
ANNOTATED_VALUES_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "values"


def slugify_doi(doi: str) -> str:
    """Convert DOI to a filesystem-safe slug."""
    return doi.replace("/", "_").replace(".", "_").replace("(", "").replace(")", "")


def extract_signature(name: str) -> str:
    """Extract a normalized journal+article signature for robust matching.

    Handles naming inconsistencies like:
    - '10.1021/acscatal.1c05800' (DOI) vs '10.1021acscatal.1c05800' (PDF filename)
    - 'acscatal.0c05126' vs '10.1021/acscatal.0c05126'
    """
    # Remove known file extensions (not arbitrary dot-splitting which breaks DOIs)
    for ext in ('.pdf', '.json', '.txt', '.docx', '.md', '.xml', '.svg', '.xlsx'):
        if name.lower().endswith(ext):
            name = name[:-len(ext)]
            break
    # Remove _SI suffix at end
    name = re.sub(r'_SI$', '', name)
    # Strip leading DOI prefix (e.g., '10.1021/', '10_1021_', '10.1021', '10_1021')
    name = re.sub(r'^10[._]?\d{4,5}[._/]?', '', name)
    # Normalize separators to underscores
    name = name.replace('/', '_').replace('.', '_').replace('-', '_')
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    return name.lower().strip('_')


def normalize_filename_for_matching(fname: str) -> str:
    """Normalize a filename or DOI slug for PDF-to-JSON matching."""
    # Remove _SI suffix
    fname = re.sub(r'_SI$', '', fname)
    return extract_signature(fname)


def build_file_map(source_dir: Path) -> Dict:
    """Build a mapping from DOI slugs to their associated files."""
    json_files = {}
    pdf_files = {}
    docx_files = {}  # Some papers have .docx main text
    other_files = {}

    for f in sorted(source_dir.iterdir()):
        if f.is_dir():
            continue
        if f.suffix == ".json":
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                doi = d.get("doi", "")
                slug = slugify_doi(doi)
                json_files[slug] = {"path": f, "doi": doi}
            except (json.JSONDecodeError, KeyError):
                other_files[f.name] = f
        elif f.suffix == ".txt":
            # Some papers have ground truth stored as .txt (JSON content)
            try:
                content = f.read_text(encoding="utf-8")
                d = json.loads(content)
                doi = d.get("doi", "")
                if doi:
                    slug = slugify_doi(doi)
                    json_files[slug] = {"path": f, "doi": doi, "is_txt": True}
                    print(f"  Note: {f.name} contains valid JSON ground truth")
                else:
                    other_files[f.name] = f
            except (json.JSONDecodeError, KeyError):
                other_files[f.name] = f
        elif f.suffix == ".pdf":
            base = f.stem
            norm = normalize_filename_for_matching(base)
            pdf_files.setdefault(norm, {})
            is_si = "_SI" in base or "_SI" in f.name
            pdf_files[norm]["si" if is_si else "main"] = f
        elif f.suffix == ".docx":
            base = f.stem
            norm = normalize_filename_for_matching(base)
            is_si = "_SI" in base or "_SI" in f.name
            if is_si:
                pdf_files.setdefault(norm, {})
                pdf_files[norm]["si_docx"] = f
            else:
                docx_files[norm] = f
        else:
            other_files[f.name] = f

    return {"json": json_files, "pdf": pdf_files, "docx": docx_files, "other": other_files}


def match_pdfs_to_jsons(file_map: Dict) -> List[Dict]:
    """Match PDFs to their corresponding JSON ground truth files using signatures."""
    papers = []
    json_data = file_map["json"]
    pdf_data = file_map["pdf"]
    docx_data = file_map.get("docx", {})

    # Build signature-based reverse lookup for JSONs
    json_sig_to_slug = {}
    for slug, info in json_data.items():
        sig = extract_signature(slug)
        json_sig_to_slug[sig] = slug
        # Also add the JSON filename stem as a fallback signature
        json_stem = info["path"].stem
        sig2 = extract_signature(json_stem)
        if sig2 != sig:
            json_sig_to_slug[sig2] = slug

    # Match PDFs by signature
    matched_jsons = set()
    for pdf_norm, pdfs in pdf_data.items():
        sig = extract_signature(pdf_norm)
        matching_slug = json_sig_to_slug.get(sig)
        if matching_slug:
            papers.append({
                "doi": json_data[matching_slug]["doi"],
                "json_file": json_data[matching_slug]["path"],
                "main_pdf": pdfs.get("main"),
                "si_pdf": pdfs.get("si"),
                "si_docx": pdfs.get("si_docx"),
            })
            matched_jsons.add(matching_slug)
        else:
            # Debug: print unmatched PDFs
            print(f"  ⚠ Unmatched PDF group: sig='{sig}', pdf_norm='{pdf_norm}', "
                  f"has_main={pdfs.get('main') is not None}, "
                  f"has_si={pdfs.get('si') is not None}")

    # Add JSONs without matching PDFs
    for slug, info in json_data.items():
        if slug not in matched_jsons:
            papers.append({
                "doi": info["doi"],
                "json_file": info["path"],
                "main_pdf": None,
                "si_pdf": None,
                "si_docx": None,
            })

    # Add docx-only papers (no JSON, just main text)
    for docx_norm, docx_file in docx_data.items():
        sig = extract_signature(docx_norm)
        if sig not in json_sig_to_slug:
            papers.append({
                "doi": f"unknown/{docx_norm}",
                "json_file": None,
                "main_pdf": docx_file,  # .docx as main text
                "si_pdf": None,
                "si_docx": None,
                "is_docx_only": True,
            })

    return papers


def copy_raw_files(papers: List[Dict]) -> None:
    """Copy paper PDFs into the organized raw directory structure."""
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)

    for i, paper in enumerate(papers, 1):
        doi = paper["doi"]
        slug = slugify_doi(doi)
        paper_dir = PAPERS_DIR / slug
        paper_dir.mkdir(exist_ok=True)

        # Copy main PDF (or docx if no PDF)
        if paper.get("main_pdf"):
            src = paper["main_pdf"]
            if src.suffix == ".docx":
                dst = paper_dir / "paper.docx"
            else:
                dst = paper_dir / "paper.pdf"
            if not dst.exists():
                shutil.copy2(src, dst)
                print(f"  [{i:02d}] Copied main: {src.name} -> papers/{slug}/{dst.name}")
            else:
                print(f"  [{i:02d}] Main already exists: papers/{slug}/{dst.name}")
        else:
            print(f"  [{i:02d}] ⚠ No main PDF/docx found for DOI: {doi}")

        # Copy SI PDF
        if paper.get("si_pdf"):
            src = paper["si_pdf"]
            dst = paper_dir / "supporting_info.pdf"
            if not dst.exists():
                shutil.copy2(src, dst)
                print(f"       Copied SI PDF: {src.name}")

        # Copy SI docx
        if paper.get("si_docx"):
            src = paper["si_docx"]
            dst = paper_dir / "supporting_info.docx"
            if not dst.exists():
                shutil.copy2(src, dst)
                print(f"       Copied SI docx: {src.name}")




def create_study_narrative(papers: List[Dict]) -> None:
    """Create a study_narrative.md describing the PETase benchmarking dataset."""
    narrative = f"""# PETase Enzyme Engineering Benchmark Dataset

## Overview

This dataset consists of {len(papers)} peer-reviewed research papers on PET
(polyethylene terephthalate) hydrolase enzyme engineering. Each paper reports
experimental data on enzyme variants, substrate properties, reaction conditions,
and kinetic parameters for the enzymatic degradation of PET plastics.

The ground truth metadata was manually curated by domain experts and covers five
categories:
1. **Substrate properties** — PET type, crystallinity, glass transition temperature (Tg), molecular weight
2. **Enzyme properties** — Enzyme variants, mutations, melting temperature (Tm)
3. **Reaction conditions (lab-scale)** — Reactor volume, enzyme/substrate loading, buffer, pH, temperature, agitation, reaction time
4. **Kinetic parameters and measurement analytics** — kcat, Km, specific activity, initial rate, quantification methods, depolymerization efficacy
5. **Bibliographic metadata** — DOI

## Domain

Enzyme engineering / biocatalysis for plastic degradation

## Experiment Type

PET hydrolase characterization and engineering — in vitro enzyme assays with
synthetic PET substrates, monitored by HPLC/UV-Vis quantification of
depolymerization products (TPA, MHET, BHET, EG).

## Papers

| # | DOI | Title (to be populated from PDF) |
|---|-----|----------------------------------|
"""
    for i, paper in enumerate(papers, 1):
        narrative += f"| {i} | `{paper['doi']}` | (extracted from paper) |\n"

    narrative += f"""
## FAIR-DS Mapping

The PETase domain-specific metadata fields have been mapped to ISA-Tab sheets:

| PETase Category | ISA Sheet | FAIR-DS Package |
|-----------------|-----------|----------------|
| Substrate properties | sample, observation unit | petase_enzyme_engineering |
| Enzyme properties | sample | petase_enzyme_engineering |
| Reaction conditions | assay, protocol | petase_enzyme_engineering |
| Kinetic parameters | observation unit | petase_enzyme_engineering |
| Bibliographic metadata | investigation | default |

## Annotation Method

- **generated_by**: manual_curation_by_domain_expert
- **Date**: 2026-06 (integration)

## Notes

- This is a domain-specific benchmark for evaluating FAIRiAgent's ability to
  extract structured metadata from enzyme engineering papers.
- The ground truth format differs from standard FAIR-DS ISA-Tab — a new
  `petase_enzyme_engineering` FAIR-DS package is proposed to capture these
  domain-specific fields.
- Not all papers have both main text and supporting information PDFs available.
- One paper (10.1021/acscatal.4c00400) has a text extraction instead of JSON.
"""
    narrative_path = RAW_DIR / "study_narrative.md"
    narrative_path.write_text(narrative, encoding="utf-8")
    print(f"\n✓ Created study narrative: {narrative_path}")


def create_paper_manifest(papers: List[Dict]) -> None:
    """Create a JSON manifest listing all papers in this dataset."""
    manifest = {
        "dataset_id": "petase_enzyme_engineering",
        "domain": "Enzyme engineering / biocatalysis for plastic degradation",
        "experiment_type": "PET hydrolase characterization and engineering",
        "annotation_date": "2026-06-08",
        "annotator": "manual_curation_by_domain_expert",
        "n_papers": len(papers),
        "papers": [],
    }
    for paper in papers:
        slug = slugify_doi(paper["doi"])
        entry = {
            "doi": paper["doi"],
            "slug": slug,
            "has_main_pdf": paper.get("main_pdf") is not None,
            "has_si_pdf": paper.get("si_pdf") is not None,
            "has_ground_truth_json": paper.get("json_file") is not None,
            "paper_path": f"papers/{slug}/paper.pdf",
        }
        if paper.get("si_pdf"):
            entry["si_path"] = f"papers/{slug}/supporting_info.pdf"
        manifest["papers"].append(entry)

    manifest_path = RAW_DIR / "paper_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Created paper manifest: {manifest_path}")


def main():
    print("=" * 70)
    print("Organizing PETase Papers Dataset")
    print("=" * 70)

    # Build file map
    print("\n[1/4] Scanning source directory...")
    file_map = build_file_map(SOURCE_DIR)

    print(f"  JSON files: {len(file_map['json'])}")
    print(f"  PDF files: {len(file_map['pdf'])} (normalized)")
    print(f"  Other files: {len(file_map['other'])}")
    for name, path in file_map["other"].items():
        print(f"    - {name}")

    # Match PDFs to JSONs
    print("\n[2/4] Matching PDFs to ground truth JSONs...")
    papers = match_pdfs_to_jsons(file_map)
    print(f"  Matched {len(papers)} papers")

    # Copy raw files
    print("\n[3/4] Copying raw files to organized structure...")
    copy_raw_files(papers)

    # Create documentation
    print("\n[4/4] Creating documentation...")
    create_study_narrative(papers)
    create_paper_manifest(papers)

    print("\n" + "=" * 70)
    print("✓ Organization complete!")
    print(f"  Raw data: {RAW_DIR}")
    print(f"  Papers directory: {PAPERS_DIR}")
    print(f"  Paper count: {len(papers)}")
    print("=" * 70)

    return papers


if __name__ == "__main__":
    papers = main()
