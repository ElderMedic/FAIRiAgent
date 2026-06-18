def test_excel_export_is_accessible_from_graph_excel():
    from fairifier.graph.excel import try_export_fairds_metadata_excel
    assert try_export_fairds_metadata_excel is not None
