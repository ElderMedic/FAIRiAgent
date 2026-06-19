#!/usr/bin/env python3
"""
PETase → FAIR-DS ISA-Tab Converter v2.0

Redesigned with assay-level decomposition:
- Each experimental condition → separate Assay row (not JSON-stringified dicts)
- Enzyme variants + substrate types → separate Sample rows
- Measurement results → Observation Unit rows
- Missing values omitted (not filled with "NA")
- Controlled vocabularies applied where available

Usage:
    python evaluation/scripts/convert_petase_to_fairds.py
"""

import json
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "PETase_papers_json"
OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "annotated" / "values"
PKG_DEF = (
    PROJECT_ROOT
    / "evaluation"
    / "config"
    / "packages"
    / "petase_enzyme_engineering_package.json"
)

# ── Controlled Vocabularies ──────────────────────────────────────────────────

SUBSTRATE_FORM_MAP = {
    "powder": "powder", "amorphous powder": "powder",
    "film": "film", "flake": "flake",
    "nanoparticle": "nanoparticle", "microplastic": "microplastic",
    "pellet": "pellet", "preform": "preform",
    "textile": "textile", "fibre": "fibre", "fiber": "fibre",
    "micronized powder": "micronized powder",
    "crystalline powder": "crystalline powder",
}

BUFFER_TYPE_MAP = {
    "potassium phosphate": "potassium phosphate",
    "sodium phosphate": "sodium phosphate",
    "glycine-naoh": "glycine-NaOH", "glycine naoh": "glycine-NaOH",
    "glycine-oh": "glycine-OH", "glycine oh": "glycine-OH",
    "tris-hcl": "Tris-HCl", "tris hcl": "Tris-HCl",
    "hepes": "HEPES", "borate": "borate",
    "phosphate": "phosphate", "water": "water",
}

ACTIVITY_UNIT_MAP = {
    "mg taeq h^-1 mg enzyme^-1": "mg_TAeq_per_h_per_mg_enzyme",
    "mg taeq h-1 mg enzyme-1": "mg_TAeq_per_h_per_mg_enzyme",
    "µmol taeq h^-1 mg enzyme^-1": "µmol_TAeq_per_h_per_mg_enzyme",
    "µmol taeq h-1 mg enzyme-1": "µmol_TAeq_per_h_per_mg_enzyme",
    "g ta l^-1 h^-1 g enzyme^-1": "g_TA_per_L_per_h_per_g_enzyme",
    "g taeq l^-1 h^-1": "g_TA_per_L_per_h_per_g_enzyme",
    "µm h^-1 mg enzyme^-1": "µM_per_h_per_mg_enzyme",
    "u/mg": "U_per_mg",
}

DETECTION_METHOD_MAP = {
    "absorbance": "absorbance", "uv": "absorbance",
    "fluorescence": "fluorescence", "fluorometric": "fluorescence",
    "refractive index": "refractive_index", "ri": "refractive_index",
    "mass spectrometry": "mass_spectrometry", "ms": "mass_spectrometry",
    "naoh titration": "NaOH_titration", "ph stat": "pH_stat",
    "ph-stat": "pH_stat", "phstat": "pH_stat",
}


# ── Helper Functions ─────────────────────────────────────────────────────────

def _is_missing(val: Any) -> bool:
    """Check if a value represents missing data."""
    if val is None:
        return True
    if isinstance(val, str) and val.strip().upper() in ("NA", "N/A", "", "NOT REPORTED"):
        return True
    return False


def _classify_buffer(buffer_str: str) -> Tuple[str, Optional[str]]:
    """Classify buffer into type and concentration."""
    buf_lower = buffer_str.lower().strip()
    buf_type = "other"
    for key, val in BUFFER_TYPE_MAP.items():
        if key in buf_lower:
            buf_type = val
            break

    # Try to extract concentration
    conc_match = re.search(r'(\d+\.?\d*)\s*(mM|M|molar|%)', buffer_str)
    concentration = f"{conc_match.group(1)} {conc_match.group(2)}" if conc_match else None

    return buf_type, concentration


def _classify_substrate_form(substrate_name: str) -> str:
    """Classify substrate form from name string."""
    name_lower = substrate_name.lower()
    for key, val in SUBSTRATE_FORM_MAP.items():
        if key in name_lower:
            return val
    return "other"


def _classify_detection(detection_str: str) -> Tuple[str, Optional[str]]:
    """Classify detection method and extract wavelength."""
    d_lower = detection_str.lower().strip()
    method = "other"
    for key, val in DETECTION_METHOD_MAP.items():
        if key in d_lower:
            method = val
            break

    # Extract wavelength
    wl_match = re.search(r'(\d{3})\s*nm', detection_str)
    wavelength = f"{wl_match.group(1)} nm" if wl_match else None

    return method, wavelength


def _extract_assay_keys(reaction_conditions: Dict, enzyme_types: List[str]) -> List[str]:
    """Identify unique assay identifiers from nested reaction condition dicts.

    Strategy:
    1. Collect all keys used across reaction condition fields.
    2. Filter out keys that are enzyme names (found in enzyme_types list).
    3. The remaining keys appearing in ≥2 fields are assay identifiers.
    4. If no multi-field keys remain, use enzyme-specific keys (one assay per enzyme).
    """
    # Normalize enzyme names for matching
    enzyme_norm = set()
    for enz in enzyme_types:
        enz_lower = enz.lower().strip()
        enzyme_norm.add(enz_lower)
        # Also add short forms (e.g., "LCC" from "LCC ICCG / F243I/...")
        short = enz_lower.split("/")[0].strip()
        enzyme_norm.add(short)

    key_counter = defaultdict(int)
    all_keys = set()
    for field, val in reaction_conditions.items():
        if isinstance(val, dict):
            for k in val.keys():
                all_keys.add(k)
                key_counter[k] += 1

    if not all_keys:
        return ["default_assay"]

    # Separate enzyme keys from assay keys
    enzyme_keys = set()
    assay_keys = set()
    for k in all_keys:
        k_lower = k.lower().strip()
        is_enzyme = False
        for enz in enzyme_norm:
            if enz in k_lower or k_lower in enz:
                is_enzyme = True
                break
        if is_enzyme:
            enzyme_keys.add(k)
        elif key_counter[k] >= 2:
            assay_keys.add(k)

    # If we found assay keys, use them
    if assay_keys:
        return sorted(assay_keys)

    # If only enzyme keys, create per-enzyme assay rows
    if enzyme_keys:
        return sorted(enzyme_keys)

    # Fallback: use any keys that appear in ≥1 field
    return sorted(all_keys)


def _get_assay_value(field_data: Any, assay_key: str, default: Any = None) -> Any:
    """Get a value for a specific assay from potentially nested data.

    Handles:
    - Simple string/number: returned as-is (same value for all assays)
    - Dict keyed by assay: returns value for specific assay key
    - Dict keyed by enzyme: returns the full dict (needs enzyme-level decomposition)
    - List: returned as-is
    """
    if isinstance(field_data, dict):
        # Try exact assay key match first
        if assay_key in field_data:
            return field_data[assay_key]
        # Try case-insensitive match
        for k, v in field_data.items():
            if k.lower() == assay_key.lower():
                return v
        # Try partial match
        for k, v in field_data.items():
            if assay_key.lower() in k.lower() or k.lower() in assay_key.lower():
                return v
        # No match — return the whole dict (enzyme-specific values)
        return field_data
    return field_data if field_data is not None else default


# ── Main Conversion Logic ────────────────────────────────────────────────────

def convert_petase_to_fairds_v2(petase_json: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a PETase domain-specific JSON to FAIR-DS ISA-Tab with assay-level decomposition.

    Returns a dict with document_id, document_source, generated_by, generated_at,
    paper_doi, and isa_sheets (investigation, study, sample, assay, observationunit).
    """
    doi = petase_json.get("doi", "")
    doi_slug = doi.replace("/", "_").replace(".", "_").replace("(", "").replace(")", "")
    doc_id = f"petase_{doi_slug}"

    # ── Extract data sections ──
    sp = petase_json.get("substrate_property", {})
    ep = petase_json.get("enzyme_property", {})
    rcl = petase_json.get("reaction_condition_lab_scale", {})
    kpma = petase_json.get("kinetic_parameters_and_measurement_analytics", {})

    # ── Extract enzyme types (needed for assay key disambiguation) ──
    enzyme_types = ep.get("type", [])
    if isinstance(enzyme_types, str):
        enzyme_types = [enzyme_types]

    # ── Identify assay keys ──
    assay_keys = _extract_assay_keys(rcl, enzyme_types)
    if not assay_keys:
        assay_keys = ["default_assay"]

    # ── Build ISA sheets ──
    isa_sheets = {
        "investigation": {"multi_row": False, "expected_rows": []},
        "study": {"multi_row": False, "expected_rows": []},
        "sample": {"multi_row": True, "expected_rows": []},
        "assay": {"multi_row": True, "expected_rows": []},
        "observationunit": {"multi_row": True, "expected_rows": []},
    }

    # ── Investigation (paper-level, 1 row) ──
    inv_row = {
        "investigation identifier": f"INV_{doi_slug[:30]}",
        "investigation title": f"PET hydrolase research — {doi}",
        "investigation description": (
            f"Enzymatic PET depolymerisation study characterising "
            f"enzyme variants, substrate specificity, reaction conditions, "
            f"and kinetic parameters."
        ),
        "investigation contentUrl": doi,
        "_evidence": f"DOI: {doi}",
    }
    # Only include author fields if we could extract them
    isa_sheets["investigation"]["expected_rows"].append(inv_row)

    # ── Study (1 row) ──
    study_row = {
        "study identifier": f"STUDY_{doi_slug[:30]}",
        "study title": f"PET hydrolase characterisation — {doi}",
        "study description": (
            f"Experimental characterisation of PET hydrolase enzymes "
            f"including substrate specificity, reaction condition "
            f"optimisation, and kinetic analysis."
        ),
        "investigation identifier": f"INV_{doi_slug[:30]}",
        "_evidence": f"DOI: {doi}",
    }
    isa_sheets["study"]["expected_rows"].append(study_row)

    # ── Sample rows (enzyme variants + substrate types) ──
    substrate_types = sp.get("type", [])
    if isinstance(substrate_types, str):
        substrate_types = [substrate_types]

    enz_ids = []
    sub_ids = []

    # Enzyme sample rows
    for i, enz in enumerate(enzyme_types):
        enz_id = f"ENZ_{doi_slug[:15]}_{i}"
        enz_ids.append(enz_id)
        sample_row = {
            "enzyme identifier": enz_id,
            "sample type": "enzyme_variant",
            "enzyme type": enz,
        }
        # Extract mutation from enzyme name (e.g., "LCC ICCG / F243I/D238C/S283C/Y127G")
        if "/" in enz:
            parts = enz.split("/", 1)
            sample_row["enzyme mutation"] = parts[1].strip()

        # Tm for this enzyme
        tm_data = kpma.get("Tm", {})
        if isinstance(tm_data, dict):
            for k, v in tm_data.items():
                if enz.lower() in k.lower() or k.lower() in enz.lower():
                    sample_row["enzyme melting temperature"] = str(v)
                    break
        elif not _is_missing(tm_data):
            sample_row["enzyme melting temperature"] = str(tm_data)

        # Only include if we have meaningful data beyond just the name
        isa_sheets["sample"]["expected_rows"].append(sample_row)

    # Substrate sample rows
    for i, sub in enumerate(substrate_types):
        sub_id = f"SUB_{doi_slug[:15]}_{i}"
        sub_ids.append(sub_id)
        sub_form = _classify_substrate_form(sub)
        sample_row = {
            "substrate identifier": sub_id,
            "sample type": "pet_substrate",
            "PET substrate type": sub,
            "substrate form factor": sub_form,
        }
        # Crystallinity for this substrate
        cryst = sp.get("crystallinity", {})
        if isinstance(cryst, dict):
            for k, v in cryst.items():
                if sub.lower() in k.lower() or k.lower() in sub.lower():
                    sample_row["PET crystallinity"] = str(v)
                    break
        elif not _is_missing(cryst):
            sample_row["PET crystallinity"] = str(cryst)

        # Tg for this substrate
        tg = sp.get("Tg", {})
        if isinstance(tg, dict):
            for k, v in tg.items():
                if sub.lower() in k.lower() or k.lower() in sub.lower():
                    sample_row["PET glass transition temperature"] = str(v)
                    break
        elif not _is_missing(tg):
            sample_row["PET glass transition temperature"] = str(tg)

        # Molecular weight
        mw = sp.get("avg_molecular_weight")
        if not _is_missing(mw):
            if isinstance(mw, dict):
                for k, v in mw.items():
                    if sub.lower() in k.lower() or k.lower() in sub.lower():
                        sample_row["PET molecular weight"] = str(v)
                        break
            else:
                sample_row["PET molecular weight"] = str(mw)

        isa_sheets["sample"]["expected_rows"].append(sample_row)

    # ── Assay rows (one per experimental condition) ──
    default_enz = enz_ids[0] if enz_ids else ""
    default_sub = sub_ids[0] if sub_ids else ""

    for ak in assay_keys:
        assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(ak)[:20]}"
        assay_row = {
            "assay identifier": assay_id,
            "assay name": _humanize_assay_name(ak),
            "study identifier": f"STUDY_{doi_slug[:30]}",
            "enzyme sample identifier": default_enz,
            "substrate sample identifier": default_sub,
            "_evidence": f"DOI: {doi}; assay: {ak}",
        }

        # Enzyme loading
        el_val = _get_assay_value(rcl.get("enzyme_loading", {}), ak)
        if not _is_missing(el_val) and not isinstance(el_val, dict):
            assay_row["enzyme loading"] = str(el_val)

        # Substrate solid loading
        ssl_val = _get_assay_value(rcl.get("substrate_solid_loading", {}), ak)
        if not _is_missing(ssl_val) and not isinstance(ssl_val, dict):
            assay_row["substrate solid loading"] = str(ssl_val)

        # Reactor volume
        rv_val = _get_assay_value(rcl.get("reactor_volume", {}), ak)
        if not _is_missing(rv_val) and not isinstance(rv_val, dict):
            assay_row["reactor volume"] = str(rv_val)

        # Buffer
        buf_val = _get_assay_value(rcl.get("buffer_type_and_concentration", {}), ak)
        if not _is_missing(buf_val):
            if isinstance(buf_val, dict):
                pass # Skipping enzyme-keyed buffer logic to be strict about columns
            else:
                buf_type, buf_conc = _classify_buffer(str(buf_val))
                assay_row["buffer type"] = buf_type
                if buf_conc:
                    assay_row["buffer concentration"] = buf_conc

        # pH
        ph_val = _get_assay_value(rcl.get("pH", {}), ak)
        if not _is_missing(ph_val) and not isinstance(ph_val, dict):
            try:
                # Extract numeric pH
                ph_match = re.search(r'(\d+\.?\d*)', str(ph_val))
                if ph_match:
                    assay_row["reaction pH"] = ph_match.group(1)
            except (ValueError, AttributeError):
                pass

        # Temperature
        temp_val = _get_assay_value(rcl.get("temperature", {}), ak)
        if not _is_missing(temp_val) and not isinstance(temp_val, dict):
            temp_str = str(temp_val)
            temp_match = re.search(r'(\d+\.?\d*)\s*°?C?', temp_str)
            if temp_match:
                assay_row["reaction temperature"] = f"{temp_match.group(1)} °C"

        # Agitation
        agit_val = _get_assay_value(rcl.get("agitation_rate", {}), ak)
        if not _is_missing(agit_val) and not isinstance(agit_val, dict):
            agit_str = str(agit_val)
            rpm_match = re.search(r'(\d+)\s*rpm', agit_str)
            if rpm_match:
                assay_row["agitation rate"] = f"{rpm_match.group(1)} rpm"

        # Reaction time
        rt_val = _get_assay_value(rcl.get("reaction_time", {}), ak)
        if not _is_missing(rt_val) and not isinstance(rt_val, dict):
            assay_row["reaction time"] = str(rt_val)

        # Real PET substrate
        proxy_val = kpma.get(
            "does_the_study_use_proxy_substrate_or_actual_PET_substrate", ""
        )
        if not _is_missing(proxy_val):
            proxy_lower = str(proxy_val).lower()
            if "actual" in proxy_lower and "proxy" not in proxy_lower:
                assay_row["actual PET vs proxy substrate"] = "yes"
            elif "proxy" in proxy_lower:
                assay_row["actual PET vs proxy substrate"] = "no"
            else:
                assay_row["actual PET vs proxy substrate"] = "both"

        # HPLC
        hplc_val = kpma.get(
            "does_the_product_analysis_use_HPLC_as_standard_quantification", ""
        )
        if not _is_missing(hplc_val):
            hplc_lower = str(hplc_val).lower()
            assay_row["analytical separation method"] = "HPLC" if "yes" in hplc_lower else "other"

        # Detection method
        det_val = kpma.get(
            "how_are_degraded_PET_monomers_quantified_absorbance_or_fluorometric", ""
        )
        if not _is_missing(det_val):
            det_method, det_wl = _classify_detection(str(det_val))
            assay_row["detection method"] = det_method
            if det_wl:
                assay_row["UV detection wavelength"] = det_wl

        isa_sheets["assay"]["expected_rows"].append(assay_row)

    # ── Observation Unit rows ──
    # Specific activity
    spec_act = kpma.get("specific_activity")
    if not _is_missing(spec_act):
        if isinstance(spec_act, dict):
            for condition, value in spec_act.items():
                assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(condition)[:20]}" if condition in assay_keys else f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
                obs_row = {
                    "observation unit identifier": f"OBS_{doi_slug[:20]}_spec_{_slugify(condition)[:20]}",
                    "assay identifier reference": assay_id,
                }
                val_str = str(value)
                num_match = re.search(r'([\d.]+)\s*(?:±\s*[\d.]+)?', val_str)
                if num_match:
                    unit_code = "U_per_mg"
                    for pattern, uc in ACTIVITY_UNIT_MAP.items():
                        if pattern in val_str.lower():
                            unit_code = uc
                            break
                    obs_row["specific activity"] = f"{num_match.group(1)} {unit_code}"
                isa_sheets["observationunit"]["expected_rows"].append(obs_row)
        else:
            assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
            obs_row = {
                "observation unit identifier": f"OBS_{doi_slug[:20]}_spec",
                "assay identifier reference": assay_id,
            }
            val_str = str(spec_act)
            num_match = re.search(r'([\d.]+)\s*(?:±\s*[\d.]+)?', val_str)
            if num_match:
                unit_code = "U_per_mg"
                for pattern, uc in ACTIVITY_UNIT_MAP.items():
                    if pattern in val_str.lower():
                        unit_code = uc
                        break
                obs_row["specific activity"] = f"{num_match.group(1)} {unit_code}"
            isa_sheets["observationunit"]["expected_rows"].append(obs_row)

    # Initial rate
    init_rate = kpma.get("initial_rate")
    if not _is_missing(init_rate):
        if isinstance(init_rate, dict):
            for condition, value in init_rate.items():
                assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(condition)[:20]}" if condition in assay_keys else f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
                obs_row = {
                    "observation unit identifier": f"OBS_{doi_slug[:20]}_ir_{_slugify(condition)[:15]}",
                    "assay identifier reference": assay_id,
                    "initial reaction rate": str(value),
                }
                isa_sheets["observationunit"]["expected_rows"].append(obs_row)
        else:
            assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
            obs_row = {
                "observation unit identifier": f"OBS_{doi_slug[:20]}_ir",
                "assay identifier reference": assay_id,
                "initial reaction rate": str(init_rate),
            }
            isa_sheets["observationunit"]["expected_rows"].append(obs_row)

    # kcat
    kcat_val = kpma.get("kcat")
    if not _is_missing(kcat_val):
        if isinstance(kcat_val, dict):
            for condition, value in kcat_val.items():
                assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(condition)[:20]}" if condition in assay_keys else f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
                isa_sheets["observationunit"]["expected_rows"].append({
                    "observation unit identifier": f"OBS_{doi_slug[:20]}_kcat_{_slugify(condition)[:15]}",
                    "assay identifier reference": assay_id,
                    "catalytic rate constant kcat": str(value),
                })
        else:
            assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
            isa_sheets["observationunit"]["expected_rows"].append({
                "observation unit identifier": f"OBS_{doi_slug[:20]}_kcat",
                "assay identifier reference": assay_id,
                "catalytic rate constant kcat": str(kcat_val),
            })

    # Km
    km_val = kpma.get("Km")
    if not _is_missing(km_val):
        if isinstance(km_val, dict):
            for condition, value in km_val.items():
                assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(condition)[:20]}" if condition in assay_keys else f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
                isa_sheets["observationunit"]["expected_rows"].append({
                    "observation unit identifier": f"OBS_{doi_slug[:20]}_km_{_slugify(condition)[:15]}",
                    "assay identifier reference": assay_id,
                    "Michaelis constant Km": str(value),
                })
        else:
            assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
            isa_sheets["observationunit"]["expected_rows"].append({
                "observation unit identifier": f"OBS_{doi_slug[:20]}_km",
                "assay identifier reference": assay_id,
                "Michaelis constant Km": str(km_val),
            })

    # T0.5
    t05_val = kpma.get("T0.5")
    if not _is_missing(t05_val):
        if isinstance(t05_val, dict):
            for condition, value in t05_val.items():
                assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(condition)[:20]}" if condition in assay_keys else f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
                isa_sheets["observationunit"]["expected_rows"].append({
                    "observation unit identifier": f"OBS_{doi_slug[:20]}_t05_{_slugify(condition)[:15]}",
                    "assay identifier reference": assay_id,
                    "half inactivation temperature": str(value),
                })
        else:
            assay_id = f"ASSAY_{doi_slug[:20]}_{_slugify(assay_keys[0])[:20]}"
            isa_sheets["observationunit"]["expected_rows"].append({
                "observation unit identifier": f"OBS_{doi_slug[:20]}_t05",
                "assay identifier reference": assay_id,
                "half inactivation temperature": str(t05_val),
            })

    return {
        "document_id": doc_id,
        "document_source": f"PET hydrolase research paper — {doi}",
        "generated_by": "PETase_v2_converter__assay_level_decomposition",
        "generated_at": "2026-06-08",
        "paper_doi": doi,
        "isa_sheets": isa_sheets,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    """Convert a string to a safe identifier slug."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', s)[:30]


def _humanize_assay_name(assay_key: str) -> str:
    """Convert an assay key like 'Gf-PET_assay' to a human-readable name."""
    return assay_key.replace("_", " ").replace("  ", " ").strip()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("PETase → FAIR-DS ISA-Tab Converter v2.0")
    print("Assay-level decomposition  |  No 'NA' fillers  |  Controlled vocab")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_files = sorted([
        f for f in SOURCE_DIR.iterdir()
        if f.suffix == ".json" or (f.suffix == ".txt" and "acscatal.4c00400" in f.name)
    ])

    stats = {
        "papers": 0, "assay_rows": 0, "sample_rows": 0,
        "obs_rows": 0, "fields_omitted": 0,
    }

    for f in json_files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            doi = d.get("doi", "")
            if not doi:
                continue
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ⚠ Skipping {f.name}: {e}")
            continue

        fairds = convert_petase_to_fairds_v2(d)
        doc_id = fairds["document_id"]

        # Count rows
        n_assay = len(fairds["isa_sheets"]["assay"]["expected_rows"])
        n_sample = len(fairds["isa_sheets"]["sample"]["expected_rows"])
        n_obs = len(fairds["isa_sheets"]["observationunit"]["expected_rows"])

        stats["papers"] += 1
        stats["assay_rows"] += n_assay
        stats["sample_rows"] += n_sample
        stats["obs_rows"] += n_obs

        print(f"  [{stats['papers']:02d}] {doi}")
        print(f"       assay={n_assay} rows, sample={n_sample} rows, obs={n_obs} rows")

        # Write individual file (matching existing convention)
        # Strip unnecessary empty sheets
        output = {
            "document_id": fairds["document_id"],
            "document_source": fairds["document_source"],
            "generated_by": fairds["generated_by"],
            "generated_at": fairds["generated_at"],
            "paper_doi": fairds["paper_doi"],
            "isa_sheets": fairds["isa_sheets"],
        }
        out_path = OUTPUT_DIR / f"ground_truth_{doc_id}_values.json"
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*70}")
    print(f"✓ Conversion complete — v2.0 assay-level decomposition")
    print(f"  Papers:             {stats['papers']}")
    print(f"  Total assay rows:   {stats['assay_rows']}")
    print(f"  Total sample rows:  {stats['sample_rows']}")
    print(f"  Total obs rows:     {stats['obs_rows']}")
    print(f"  Output directory:   {OUTPUT_DIR}")
    print(f"{'='*70}")
    return stats


if __name__ == "__main__":
    main()
