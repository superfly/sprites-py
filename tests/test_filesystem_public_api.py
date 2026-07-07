from __future__ import annotations

import json

import httpx
import pytest

from sprites.exceptions import FileNotFoundError_


def test_sprite_filesystem_builds_pathlike_objects(make_mock_client) -> None:
    client = make_mock_client(lambda request: httpx.Response(500))
    fs = client.sprite("demo").filesystem("/app")

    path = fs.path("logs", "app.log")

    assert repr(fs) == "SpriteFilesystem(sprite='demo', working_dir='/app')"
    assert str(fs.cwd) == "/app"
    assert str(fs.root) == "/"
    assert str(path) == "/app/logs/app.log"
    assert path.name == "app.log"
    assert path.stem == "app"
    assert path.suffix == ".log"
    assert path.suffixes == [".log"]
    assert str(path.parent) == "/app/logs"
    assert path.parts == ("/", "app", "logs", "app.log")
    assert path.is_absolute() is True
    assert path.is_relative_to("/app") is True
    assert str(path.with_name("other.txt")) == "/app/logs/other.txt"
    assert str(path.with_stem("server")) == "/app/logs/server.log"
    assert str(path.with_suffix(".txt")) == "/app/logs/app.txt"


def test_filesystem_operations_use_current_api_shape(make_mock_client) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url).startswith("https://api.test/v1/sprites/demo%20fs/fs/")

        if request.url.path.endswith("/list"):
            params = dict(request.url.params)
            assert params["workingDir"] == "/app"
            if params["path"] == "/app/notes.txt":
                return httpx.Response(
                    200,
                    json={
                        "entries": [
                            {
                                "name": "notes.txt",
                                "path": "/app/notes.txt",
                                "size": 5,
                                "mode": "0644",
                                "modTime": "2026-01-12T21:24:42Z",
                                "isDir": False,
                            }
                        ]
                    },
                )
            if params["path"] == "/app/data":
                return httpx.Response(
                    200,
                    json={
                        "path": "/app/data",
                        "entries": [
                            {"name": "a.txt", "path": "/app/data/a.txt"},
                            {"name": "b", "path": "/app/data/b"},
                        ],
                    },
                )
            return httpx.Response(404, json={"error": "missing"})

        if request.url.path.endswith("/read"):
            assert request.url.params["path"] == "/app/notes.txt"
            return httpx.Response(200, content=b"hello")

        if request.url.path.endswith("/write"):
            assert request.method == "PUT"
            assert dict(request.url.params) == {
                "path": "/app/notes.txt",
                "workingDir": "/app",
                "mode": "0600",
                "mkdirParents": "false",
            }
            assert request.content == b"updated"
            return httpx.Response(200)

        if request.url.path.endswith("/delete"):
            assert request.method == "DELETE"
            assert dict(request.url.params) == {
                "path": "/app/notes.txt",
                "workingDir": "/app",
                "recursive": "false",
            }
            return httpx.Response(204)

        body = json.loads(request.content)
        if request.url.path.endswith("/rename"):
            assert body == {
                "source": "/app/notes.txt",
                "dest": "/app/renamed.txt",
                "workingDir": "/app",
            }
            return httpx.Response(200)

        if request.url.path.endswith("/copy"):
            assert body == {
                "source": "/app/renamed.txt",
                "dest": "/tmp/copy.txt",
                "workingDir": "/app",
                "recursive": False,
            }
            return httpx.Response(200)

        if request.url.path.endswith("/chmod"):
            assert body == {
                "path": "/tmp/copy.txt",
                "workingDir": "/app",
                "mode": "0755",
                "recursive": True,
            }
            return httpx.Response(200)

        raise AssertionError(f"Unexpected filesystem path: {request.url.path}")

    client = make_mock_client(handler)
    fs = client.sprite("demo fs").filesystem("/app")
    notes = fs / "notes.txt"

    stat = notes.stat()
    assert stat.name == "notes.txt"
    assert stat.size == 5
    assert stat.is_file is True
    assert notes.read_text() == "hello"

    notes.write_text("updated", mode=0o600, mkdir_parents=False)
    assert (fs / "data").listdir() == ["a.txt", "b"]
    notes.unlink()
    renamed = notes.rename("renamed.txt")
    copied = renamed.copy_to("/tmp/copy.txt", recursive=False)
    copied.chmod(0o755, recursive=True)

    assert str(renamed) == "/app/renamed.txt"
    assert str(copied) == "/tmp/copy.txt"
    assert [request.method for request in requests] == [
        "GET",
        "GET",
        "PUT",
        "GET",
        "DELETE",
        "POST",
        "POST",
        "POST",
    ]


def test_filesystem_exists_and_missing_ok_handle_not_found(make_mock_client) -> None:
    delete_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/list"):
            return httpx.Response(404, json={"error": "missing"})
        if request.url.path.endswith("/delete"):
            delete_requests.append(request)
            return httpx.Response(404, json={"error": "missing"})
        raise AssertionError(f"Unexpected filesystem path: {request.url.path}")

    client = make_mock_client(handler)
    missing = client.sprite("demo").filesystem("/app") / "missing.txt"

    assert missing.exists() is False
    assert missing.is_file() is False
    assert missing.is_dir() is False
    missing.unlink(missing_ok=True)

    with pytest.raises(FileNotFoundError_):
        missing.unlink()

    assert len(delete_requests) == 2
