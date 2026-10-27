"""Optional Firebase Storage + Firestore adapter for user file uploads.

Enable by setting FIREBASE_SERVICE_ACCOUNT_JSON and FIREBASE_STORAGE_BUCKET.
Credentials are read only from server environment variables and never returned to clients.
When not configured, the application keeps using its temporary local file store.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

_APP = None
_BUCKET = None
_FIRESTORE = None


def configured() -> bool:
    return bool(os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
                and os.getenv("FIREBASE_STORAGE_BUCKET", "").strip())


def owner_hash(owner: str) -> str:
    return hashlib.sha256(str(owner).encode("utf-8")).hexdigest()


def _clients():
    global _APP, _BUCKET, _FIRESTORE
    if not configured():
        raise RuntimeError("Firebase storage is not configured.")
    if _APP is not None and _BUCKET is not None and _FIRESTORE is not None:
        return _APP, _BUCKET, _FIRESTORE
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, storage
        raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        service_account = json.loads(raw)
        if not isinstance(service_account, dict) or not service_account.get("client_email") or not service_account.get("private_key"):
            raise ValueError("The service-account JSON is missing required fields.")
        app_name = "madx-file-storage"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            options: dict[str, Any] = {"storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()}
            project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip() or str(service_account.get("project_id", ""))
            if project_id:
                options["projectId"] = project_id
            app = firebase_admin.initialize_app(credentials.Certificate(service_account), options=options, name=app_name)
        bucket = storage.bucket(app=app)
        firestore_db = firestore.client(app=app)
        _APP, _BUCKET, _FIRESTORE = app, bucket, firestore_db
        return _APP, _BUCKET, _FIRESTORE
    except Exception as exc:
        raise RuntimeError(f"Firebase initialization failed ({type(exc).__name__}). Check service-account JSON, bucket, Firestore enablement and permissions.") from exc


def status() -> dict[str, Any]:
    configured_flag = configured()
    try:
        import firebase_admin  # noqa: F401
        sdk_installed = True
    except Exception:
        sdk_installed = False
    return {
        "backend": "firebase" if configured_flag else "local_ephemeral",
        "configured": configured_flag,
        "sdk_installed": sdk_installed,
        "storage_bucket_configured": bool(os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()),
        "service_account_configured": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()),
        "persistent_files": configured_flag and sdk_installed,
        "note": ("Firebase Storage is selected for uploads and generated project ZIPs; permissions are confirmed by an actual storage operation." if configured_flag
                 else "Firebase is optional. Configure service-account JSON and a Storage bucket to persist uploads and generated project ZIPs; local files are ephemeral on Render."),
    }


def upload_file(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    _, bucket, firestore_db = _clients()
    owner = str(meta.get("owner", ""))
    if not owner:
        raise ValueError("Upload owner is missing.")
    user_key = owner_hash(owner)
    file_id = str(meta["id"])
    blob_path = f"madx-user-files/{user_key}/{file_id}.blob"
    blob = bucket.blob(blob_path)
    blob.metadata = {"madx_file_id": file_id, "owner_hash": user_key, "sha256": str(meta.get("sha256", ""))}
    try:
        blob.upload_from_filename(str(path), content_type=str(meta.get("mime_type") or "application/octet-stream"))
        document = {key: value for key, value in meta.items() if key != "owner"}
        document.update({"owner_hash": user_key, "blob_path": blob_path, "storage_backend": "firebase"})
        firestore_db.collection("madx_files").document(file_id).set(document)
        return document
    except Exception:
        try:
            blob.delete()
        except Exception:
            pass
        raise


def get_metadata(file_id: str) -> Optional[dict[str, Any]]:
    _, _, firestore_db = _clients()
    snapshot = firestore_db.collection("madx_files").document(file_id).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    data.setdefault("id", file_id)
    return data


def list_files(owner: str, limit: int = 200) -> list[dict[str, Any]]:
    _, _, firestore_db = _clients()
    key = owner_hash(owner)
    snapshots = firestore_db.collection("madx_files").where("owner_hash", "==", key).limit(min(max(limit, 1), 200)).stream()
    rows = [doc.to_dict() or {} for doc in snapshots]
    rows.sort(key=lambda row: int(row.get("uploaded_at", 0)), reverse=True)
    for row in rows:
        row.setdefault("id", "")
    return rows


def download_file(meta: dict[str, Any]) -> bytes:
    _, bucket, _ = _clients()
    blob_path = str(meta.get("blob_path", ""))
    if not blob_path.startswith("madx-user-files/"):
        raise RuntimeError("Firebase file path is invalid.")
    return bucket.blob(blob_path).download_as_bytes()


def delete_file(meta: dict[str, Any]) -> None:
    _, bucket, firestore_db = _clients()
    file_id = str(meta.get("id", ""))
    blob_path = str(meta.get("blob_path", ""))
    if blob_path.startswith("madx-user-files/"):
        try:
            bucket.blob(blob_path).delete()
        except Exception as exc:
            # A missing object is tolerated, but other errors surface to the caller.
            if "404" not in str(exc) and "NotFound" not in type(exc).__name__:
                raise
    firestore_db.collection("madx_files").document(file_id).delete()


def upload_project_artifact(owner: str, project_id: str, data: bytes) -> str:
    """Persist one generated ZIP under an owner-scoped Firebase Storage key."""
    _, bucket, _ = _clients()
    if not owner or not project_id or not isinstance(data, (bytes, bytearray)):
        raise ValueError("Project artifact metadata or bytes are invalid.")
    owner_key = owner_hash(owner)
    object_name = f"madx-project-artifacts/{owner_key}/{project_id}.zip"
    blob = bucket.blob(object_name)
    blob.metadata = {"madx_project_id": project_id, "owner_hash": owner_key}
    blob.upload_from_string(bytes(data), content_type="application/zip")
    return "firebase://" + object_name


def download_project_artifact(storage_ref: str) -> bytes:
    """Download a project ZIP from a server-stored Firebase object reference."""
    _, bucket, _ = _clients()
    object_name = str(storage_ref or "")
    if object_name.startswith("firebase://"):
        object_name = object_name[len("firebase://"):]
    if not object_name.startswith("madx-project-artifacts/") or ".." in Path(object_name).parts:
        raise RuntimeError("Firebase project artifact reference is invalid.")
    return bucket.blob(object_name).download_as_bytes()


def delete_project_artifact(storage_ref: str) -> None:
    """Delete a generated ZIP using a validated server-stored Firebase reference."""
    _, bucket, _ = _clients()
    object_name = str(storage_ref or "")
    if object_name.startswith("firebase://"):
        object_name = object_name[len("firebase://"):]
    if not object_name.startswith("madx-project-artifacts/") or ".." in Path(object_name).parts:
        raise RuntimeError("Firebase project artifact reference is invalid.")
    bucket.blob(object_name).delete()
