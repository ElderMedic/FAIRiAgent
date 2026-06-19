def test_import_node_runners():
    from fairifier.graph.nodes import ReadFileNode, OrchestrateNode, FinalizeNode
    assert ReadFileNode is not None
    assert OrchestrateNode is not None
    assert FinalizeNode is not None


def test_node_dynamic_method_copying():
    from fairifier.graph.nodes import ReadFileNode
    from fairifier.graph.app import FAIRifierLangGraphApp
    import unittest.mock as mock

    # Create an app instance
    app = object.__new__(FAIRifierLangGraphApp)
    
    # Define an override method
    mock_read = mock.MagicMock()
    app._read_single_document_content = mock_read

    # Initialize node
    node = ReadFileNode(app)

    # Verify that the overridden method was copied onto the node instance
    assert node._read_single_document_content == mock_read


def test_node_property_delegation():
    from fairifier.graph.nodes import ReadFileNode
    from fairifier.graph.app import FAIRifierLangGraphApp
    import unittest.mock as mock

    # Create an app instance
    app = object.__new__(FAIRifierLangGraphApp)
    app.mineru_client = mock.MagicMock()
    app.mineru_tool = mock.MagicMock()

    # Initialize node without passing them explicitly
    node = ReadFileNode(app)

    # Properties should delegate to app
    assert node.mineru_client == app.mineru_client
    assert node.mineru_tool == app.mineru_tool
