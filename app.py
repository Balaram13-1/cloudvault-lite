import logging
import os
import re
import sqlite3
from functools import wraps

import boto3
import click
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.logger.setLevel(logging.INFO)

BUCKET = os.environ.get("BUCKET_NAME", "cloud-vaultbucket")
REGION = os.environ.get("AWS_REGION", "ap-south-1")
DB_PATH = os.environ.get("DB_PATH", "users.db")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "txt", "docx"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@+-]{3,64}$")

s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
)


# ---------- database ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "username TEXT UNIQUE NOT NULL, "
            "password_hash TEXT NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()


def find_user(username):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()


init_db()


@app.cli.command("create-user")
@click.argument("username")
@click.password_option()
def create_user(username, password):
    """Create a CloudVault user."""
    if not USERNAME_RE.match(username):
        raise click.ClickException("Username: 3-64 chars, letters, digits . _ @ + -")
    if len(password) < 8:
        raise click.ClickException("Password must be at least 8 characters")
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise click.ClickException("User already exists")
    finally:
        conn.close()
    click.echo(f"Created user {username}")


# ---------- helpers ----------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "Login required"}), 401
        return view(*args, **kwargs)

    return wrapped


def user_prefix():
    return f"users/{session['user']}/"


def allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large (max 10 MB)"}), 413


@app.after_request
def set_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if not request.path.startswith("/static"):
        # Pages and API answers belong to one logged-in user: never cache them.
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------- pages ----------
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login_page"))
    return render_template("index.html", user=session["user"], region=REGION)


@app.route("/login")
def login_page():
    if "user" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ---------- auth ----------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = find_user(username)
    if not user or not check_password_hash(user["password_hash"], password):
        app.logger.warning("login_failed user=%r ip=%s", username[:64], request.remote_addr)
        return jsonify({"error": "Invalid username or password"}), 401
    session.clear()
    session["user"] = user["username"]
    app.logger.info("login_ok user=%s ip=%s", user["username"], request.remote_addr)
    return jsonify({"message": "Logged in", "user": user["username"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    app.logger.info("logout user=%s", session.get("user"))
    session.clear()
    return jsonify({"message": "Logged out"})


@app.route("/api/me")
@login_required
def me():
    return jsonify({"user": session["user"]})


# ---------- files ----------
@app.route("/api/files")
@login_required
def list_files():
    prefix = user_prefix()
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    except ClientError as e:
        return jsonify({"error": e.response["Error"]["Code"]}), 500
    files = [
        {
            "name": o["Key"][len(prefix):],
            "size": o["Size"],
            "modified": o["LastModified"].isoformat(),
        }
        for o in resp.get("Contents", [])
        if o["Key"][len(prefix):]
    ]
    return jsonify({"files": files})


@app.route("/api/upload", methods=["POST"])
@login_required
def upload():
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    name = secure_filename(file.filename)
    if not name or not allowed(name):
        return jsonify({"error": "File type not allowed"}), 400
    try:
        s3.upload_fileobj(
            file,
            BUCKET,
            user_prefix() + name,
            ExtraArgs={
                "ServerSideEncryption": "AES256",
                "ContentType": file.mimetype or "application/octet-stream",
            },
        )
    except ClientError as e:
        return jsonify({"error": e.response["Error"]["Code"]}), 500
    app.logger.info("upload user=%s file=%r", session["user"], name)
    return jsonify({"message": "Uploaded", "name": name}), 201


@app.route("/api/download/<name>")
@login_required
def download(name):
    key = user_prefix() + name
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return jsonify({"error": "File not found"}), 404
        return jsonify({"error": e.response["Error"]["Code"]}), 500
    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{name}"',
        },
        ExpiresIn=60,
    )
    app.logger.info("download_link user=%s file=%r", session["user"], name)
    return jsonify({"url": url, "expires_in": 60})


@app.route("/api/files/<name>", methods=["DELETE"])
@login_required
def delete(name):
    try:
        s3.delete_object(Bucket=BUCKET, Key=user_prefix() + name)
    except ClientError as e:
        return jsonify({"error": e.response["Error"]["Code"]}), 500
    app.logger.info("delete user=%s file=%r", session["user"], name)
    return jsonify({"message": "Deleted", "name": name})


if __name__ == "__main__":
    app.run(debug=True)
