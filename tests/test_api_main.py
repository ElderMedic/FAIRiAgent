from fastapi.testclient import TestClient

import fairifier.apps.api.main as api_main


def test_spa_fallback_blocks_path_traversal(
    monkeypatch, tmp_path
):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "assets").mkdir()
    index_path = dist_dir / "index.html"
    index_path.write_text(
        "<html>index</html>", encoding="utf-8"
    )
    asset_path = dist_dir / "app.txt"
    asset_path.write_text(
        "frontend asset", encoding="utf-8"
    )

    secret_path = tmp_path / "secret.txt"
    secret_path.write_text(
        "outside dist", encoding="utf-8"
    )

    monkeypatch.setattr(
        api_main, "FRONTEND_DIST", dist_dir
    )
    app = api_main.create_app(serve_frontend=True)

    with TestClient(app) as client:
        inside = client.get("/app.txt")
        assert inside.status_code == 200
        assert inside.text == "frontend asset"

        traversal = client.get("/%2E%2E/secret.txt")
        assert traversal.status_code == 200
        assert traversal.text == "<html>index</html>"
        assert "outside dist" not in traversal.text


def test_resolve_frontend_file_rejects_paths_outside_dist(
    tmp_path,
):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    inside = dist_dir / "asset.txt"
    inside.write_text("ok", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    assert (
        api_main._resolve_frontend_file(
            dist_dir, "asset.txt"
        )
        == inside.resolve()
    )
    assert (
        api_main._resolve_frontend_file(
            dist_dir, "../secret.txt"
        )
        is None
    )
