from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


class ChunkedUploadServiceError(Exception):
    pass


@dataclass
class ChunkedUploadService:
    base_folder: str
    chunk_size_bytes: int = 4 * 1024 * 1024
    max_age_seconds: int = 6 * 60 * 60

    def __post_init__(self) -> None:
        self.base_folder = os.path.abspath(self.base_folder)
        if self.chunk_size_bytes <= 0:
            raise ValueError("chunk_size_bytes must be positive")
        if self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")

    def _uploads_root(self) -> str:
        path = os.path.join(self.base_folder, ".upload_chunks")
        os.makedirs(path, exist_ok=True)
        return path

    def _session_dir(self, upload_id: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", str(upload_id or "")):
            raise ChunkedUploadServiceError("upload_id が不正です")
        return os.path.join(self._uploads_root(), upload_id)

    def _meta_path(self, upload_id: str) -> str:
        return os.path.join(self._session_dir(upload_id), "meta.json")

    def _chunk_path(self, upload_id: str, chunk_index: int) -> str:
        return os.path.join(self._session_dir(upload_id), f"chunk_{chunk_index:06d}.part")

    def _write_meta(self, upload_id: str, meta: Dict[str, Any]) -> None:
        meta_path = self._meta_path(upload_id)
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(meta_path),
            prefix="meta_",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, meta_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _read_meta(self, upload_id: str) -> Dict[str, Any]:
        meta_path = self._meta_path(upload_id)
        if not os.path.exists(meta_path):
            raise ChunkedUploadServiceError("アップロードセッションが見つかりません")
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            raise ChunkedUploadServiceError(f"メタデータの読み込みに失敗しました: {str(e)}")
        if not isinstance(meta, dict):
            raise ChunkedUploadServiceError("アップロードセッションが不正です")
        return meta

    def cleanup_expired_sessions(self) -> int:
        root = self._uploads_root()
        now = int(time.time())
        removed = 0
        for name in os.listdir(root):
            session_dir = os.path.join(root, name)
            if not os.path.isdir(session_dir):
                continue
            stale = False
            try:
                meta = self._read_meta(name)
                updated_at = int(meta.get("updated_at") or meta.get("created_at") or 0)
                if updated_at <= 0:
                    updated_at = int(os.path.getmtime(session_dir))
                stale = (now - updated_at) > self.max_age_seconds
            except Exception:
                try:
                    stale = (now - int(os.path.getmtime(session_dir))) > self.max_age_seconds
                except OSError:
                    stale = True
            if stale:
                try:
                    shutil.rmtree(session_dir, ignore_errors=True)
                    removed += 1
                except Exception:
                    pass
        return removed

    def create_session(
        self,
        *,
        pdf_name: str,
        original_filename: str,
        dest_pdf_path: str,
        total_size: int,
        total_chunks: int,
        last_modified_sec: Optional[float],
    ) -> Dict[str, Any]:
        if total_size <= 0:
            raise ChunkedUploadServiceError("size が不正です")
        if total_chunks <= 0:
            raise ChunkedUploadServiceError("total_chunks が不正です")

        dest_pdf_path = os.path.abspath(dest_pdf_path)
        if os.path.commonpath([self.base_folder, dest_pdf_path]) != self.base_folder:
            raise ChunkedUploadServiceError("保存先パスが不正です")

        upload_id = uuid.uuid4().hex
        now = int(time.time())
        meta = {
            "upload_id": upload_id,
            "pdf_name": pdf_name,
            "original_filename": original_filename,
            "dest_pdf_path": dest_pdf_path,
            "total_size": int(total_size),
            "total_chunks": int(total_chunks),
            "chunk_size": int(self.chunk_size_bytes),
            "last_modified_sec": last_modified_sec,
            "created_at": now,
            "updated_at": now,
        }
        self._write_meta(upload_id, meta)
        return {
            "upload_id": upload_id,
            "chunk_size": self.chunk_size_bytes,
            "total_chunks": total_chunks,
            "pdf_name": pdf_name,
        }

    def save_chunk(self, *, upload_id: str, chunk_index: int, file_obj) -> None:
        meta = self._read_meta(upload_id)
        total_chunks = int(meta.get("total_chunks") or 0)
        if chunk_index < 0 or chunk_index >= total_chunks:
            raise ChunkedUploadServiceError("chunk_index が範囲外です")

        session_dir = self._session_dir(upload_id)
        os.makedirs(session_dir, exist_ok=True)
        chunk_path = self._chunk_path(upload_id, chunk_index)

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=session_dir,
            prefix=f"chunk_{chunk_index:06d}_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "wb") as out:
                shutil.copyfileobj(file_obj, out)
            os.replace(tmp_path, chunk_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        meta["updated_at"] = int(time.time())
        self._write_meta(upload_id, meta)

    def complete_session(self, *, upload_id: str) -> Dict[str, Any]:
        meta = self._read_meta(upload_id)
        dest_pdf_path = os.path.abspath(str(meta.get("dest_pdf_path") or ""))
        if not dest_pdf_path:
            raise ChunkedUploadServiceError("保存先パスが不正です")
        if os.path.commonpath([self.base_folder, dest_pdf_path]) != self.base_folder:
            raise ChunkedUploadServiceError("保存先パスが不正です")

        if os.path.exists(dest_pdf_path):
            raise ChunkedUploadServiceError(f"同名のPDFが既に存在します: {meta.get('pdf_name')}.pdf")

        total_chunks = int(meta.get("total_chunks") or 0)
        if total_chunks <= 0:
            raise ChunkedUploadServiceError("チャンク情報が不正です")

        os.makedirs(os.path.dirname(dest_pdf_path), exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="upload_chunked_", suffix=".pdf", dir=self.base_folder)
        os.close(tmp_fd)

        try:
            with open(tmp_path, "wb") as out:
                for idx in range(total_chunks):
                    part_path = self._chunk_path(upload_id, idx)
                    if not os.path.exists(part_path):
                        raise ChunkedUploadServiceError(f"チャンクが不足しています: {idx + 1}/{total_chunks}")
                    with open(part_path, "rb") as f:
                        shutil.copyfileobj(f, out)

            os.replace(tmp_path, dest_pdf_path)

            last_modified_sec = meta.get("last_modified_sec")
            if last_modified_sec is not None:
                try:
                    sec = float(last_modified_sec)
                    st = os.stat(dest_pdf_path)
                    os.utime(dest_pdf_path, (st.st_atime, sec))
                except Exception:
                    pass

            return {
                "pdf_name": str(meta.get("pdf_name") or ""),
                "dest_pdf_path": dest_pdf_path,
            }
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            try:
                shutil.rmtree(self._session_dir(upload_id), ignore_errors=True)
            except Exception:
                pass
