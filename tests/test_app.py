"""Tests for CloudVault Lite. S3 is replaced by an in-memory fake, so no AWS access is needed."""
import datetime
import io
import os
import sys
import tempfile

import pytest
from botocore.exceptions import ClientError
from werkzeug.security import generate_password_hash

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "users.db")
os.environ["SECRET_KEY"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod  # noqa: E402

PASSWORD = "TestPass123"


class FakeS3:
    """Just enough of the boto3 S3 client for the routes in app.py."""

    def __init__(self):
        self.store = {}

    def list_objects_v2(self, Bucket, Prefix=""):
        items = [
            {"Key": k, "Size": len(v), "LastModified": datetime.datetime.now(datetime.timezone.utc)}
            for k, v in self.store.items()
            if k.startswith(Prefix)
        ]
        return {"Contents": items} if items else {}

    def upload_fileobj(self, fileobj, Bucket, Key, ExtraArgs=None):
        self.store[Key] = fileobj.read()

    def head_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://example.invalid/{Params['Key']}?expires={ExpiresIn}"

    def delete_object(self, Bucket, Key):
        self.store.pop(Key, None)


@pytest.fixture(scope="module", autouse=True)
def users():
    conn = appmod.get_db()
    for name in ("alice@example.com", "bob@example.com"):
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)",
            (name, generate_password_hash(PASSWORD)),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def fake_s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(appmod, "s3", fake)
    return fake


@pytest.fixture
def client(fake_s3):
    return appmod.app.test_client()


def login(client, username="alice@example.com", password=PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})


def upload(client, name="notes.txt", content=b"hello"):
    return client.post(
        "/api/upload",
        data={"file": (io.BytesIO(content), name)},
        content_type="multipart/form-data",
    )


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_api_requires_login(client):
    assert client.get("/api/files").status_code == 401
    assert client.get("/api/me").status_code == 401
    assert upload(client).status_code == 401
    assert client.delete("/api/files/notes.txt").status_code == 401


def test_pages_redirect_when_logged_out(client):
    res = client.get("/")
    assert res.status_code == 302 and res.headers["Location"].endswith("/login")
    assert client.get("/login").status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client):
    wrong = login(client, password="wrong-password")
    unknown = login(client, username="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json()


def test_login_then_dashboard_and_logout(client):
    assert login(client).status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/me").get_json() == {"user": "alice@example.com"}
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


def test_upload_list_download_delete(client, fake_s3):
    login(client)
    assert client.get("/api/files").get_json() == {"files": []}

    assert upload(client, "notes.txt", b"hello").status_code == 201
    files = client.get("/api/files").get_json()["files"]
    assert [f["name"] for f in files] == ["notes.txt"]
    assert files[0]["size"] == 5
    assert "users/alice@example.com/notes.txt" in fake_s3.store

    link = client.get("/api/download/notes.txt").get_json()
    assert link["expires_in"] == 60 and "notes.txt" in link["url"]

    assert client.delete("/api/files/notes.txt").status_code == 200
    assert client.get("/api/files").get_json() == {"files": []}


def test_upload_rejects_bad_type_and_empty_request(client):
    login(client)
    assert upload(client, "virus.exe").status_code == 400
    assert client.post("/api/upload").status_code == 400


def test_filename_is_sanitised(client, fake_s3):
    login(client)
    assert upload(client, "../../etc/passwd.txt").status_code == 201
    assert all(k.startswith("users/alice@example.com/") and ".." not in k for k in fake_s3.store)


def test_users_cannot_see_each_others_files(client, fake_s3):
    login(client, "alice@example.com")
    upload(client, "private.txt")
    client.post("/api/logout")

    login(client, "bob@example.com")
    assert client.get("/api/files").get_json() == {"files": []}
    assert client.get("/api/download/private.txt").status_code == 404


def test_download_missing_file_is_404(client):
    login(client)
    assert client.get("/api/download/missing.txt").status_code == 404


def test_security_headers_and_no_store(client):
    res = client.get("/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Cache-Control"] == "no-store"


def test_failed_login_is_logged_without_the_password(client, caplog):
    with caplog.at_level("INFO"):
        login(client, password="wrong-password")
        login(client)
    assert "login_failed" in caplog.text
    assert "login_ok" in caplog.text
    assert "wrong-password" not in caplog.text
    assert PASSWORD not in caplog.text
