

def _project(html):
    from fairifier.services.publication_tables import _TableGrid

    grid = _TableGrid(html)
    grid.feed(html)
    return grid.project()


def test_all_td_multirow_header_is_inferred_from_spans():
    html = (
        "<table><tr><td rowspan=\"2\">Substrate</td><td colspan=\"2\">Km (mM)</td></tr>"
        "<tr><td>EnzA</td><td>EnzB</td></tr>"
        "<tr><td>S1</td><td>1.15 ± 0.01</td><td>5.28</td></tr></table>"
    )
    table = _project(html)
    assert table["header_status"] == "inferred"
    assert table["columns"] == ["Substrate", "Km (mM) | EnzA", "Km (mM) | EnzB"]
    assert table["rows"] == [
        {"Substrate": "S1", "Km (mM) | EnzA": "1.15 ± 0.01", "Km (mM) | EnzB": "5.28"}
    ]


def test_all_td_text_table_keeps_headers_unresolved():
    html = (
        "<table><tr><td>Primers</td><td>Sequence</td></tr>"
        "<tr><td>F1</td><td>ATGCGT</td></tr></table>"
    )
    assert _project(html)["header_status"] == "unresolved"


def test_plain_text_top_row_over_numbers_is_an_inferred_header():
    from fairifier.services.publication_tables import render_table_rows

    html = ("<table><tr><td>Enzyme</td><td>Km (mM)</td><td>kcat (s-1)</td></tr>"
            "<tr><td>LCC</td><td>1.15 ± 0.01</td><td>7.3</td></tr></table>")
    assert _project(html)["header_status"] == "inferred"
    assert render_table_rows(html) == ["Enzyme = LCC; Km (mM) = 1.15 ± 0.01; kcat (s-1) = 7.3"]
    # A top row holding a plain number may itself be data.
    assert _project(html.replace("Km (mM)", "55"))["header_status"] == "unresolved"


def test_condition_levels_over_unitless_cells_are_an_inferred_header():
    from fairifier.services.publication_tables import render_table_rows

    html = ("<table><tr><td>Enzyme</td><td>55 °C</td><td>70 °C</td></tr>"
            "<tr><td>wild-type</td><td>3.93 ± 0.57</td><td>Not tested</td></tr></table>")
    assert render_table_rows(html) == ["Enzyme = wild-type; 55 °C = 3.93 ± 0.57; 70 °C = Not tested"]
    # The same unit under the label too: the top row may be a data row.
    assert render_table_rows(html.replace("3.93 ± 0.57", "60 °C")) == []


def test_numbers_in_math_markup_with_footnote_marks_render_as_numbers():
    from fairifier.services.publication_tables import render_table_rows

    html = ("<table><tr><td>Annealing condition</td><td>\\( X_{C} \\)[%]</td></tr>"
            "<tr><td>5 min at 85 °C</td><td>\\( 8.6 ± 0.8^{\\text{ab}} \\)</td></tr></table>")
    assert render_table_rows(html) == ["Annealing condition = 5 min at 85 °C; \\( X_{C} \\)[%] = 8.6 ± 0.8"]


def test_bare_table_quantity_takes_its_header_unit_only_when_unambiguous():
    from fairifier.agents.isa_value_mapper import ISAValueMapperAgent
    from fairifier.services.publication_tables import with_derived_table_rows

    source = with_derived_table_rows(
        "<table><tr><td rowspan=\"2\">Substrate</td><td colspan=\"2\">Km (mM)</td>"
        "<td colspan=\"2\">\\( k_{cat} \\) (\\( sec^{-1} \\))</td></tr>"
        "<tr><td>A</td><td>B</td><td>A</td><td>B</td></tr>"
        "<tr><td>S1</td><td>1.15 ± 0.01</td><td>7</td><td>130.9</td><td>7</td></tr></table>"
    )
    knowledge = [
        {"term": "Michaelis constant Km", "metadata": {"isa_sheet": "assay", "example": "230 uM"}},
        {"term": "catalytic rate constant kcat", "metadata": {"isa_sheet": "assay", "example": "12.4 s^-1"}},
        {"term": "measurement value", "metadata": {"isa_sheet": "assay", "example": "539.9"}},
    ]
    matrix = {"assay": {"rows": [{
        "michaelis constant km": "1.15 ± 0.01",
        "catalytic rate constant kcat": "130.9",
        "measurement value": "130.9",
    }, {
        "catalytic rate constant kcat": "7",  # under both mM and sec^-1: ambiguous
    }]}}

    matrix, _ = ISAValueMapperAgent._attach_table_header_units(matrix, knowledge, source)

    first, second = matrix["assay"]["rows"]
    assert first["michaelis constant km"] == "1.15 ± 0.01 mM"
    assert first["catalytic rate constant kcat"] == "130.9 sec^-1"
    assert first["measurement value"] == "130.9"  # scalar field keeps its own unit column
    assert second["catalytic rate constant kcat"] == "7"
