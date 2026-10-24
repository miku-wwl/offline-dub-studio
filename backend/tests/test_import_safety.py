import hashlib
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.media import MediaError


@pytest.fixture
def media_api(tmp_path, monkeypatch):
    api=importlib.import_module("app.main")
    config=Settings(data_dir=tmp_path / "data",models_dir=tmp_path / "models")
    config.prepare()
    database=Database(config.db_path)
    database.init()
    monkeypatch.setattr(api,"settings",config)
    monkeypatch.setattr(api,"db",database)
    return api,config


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_invalid_inbox_media_survives_repeated_validation_failure(media_api,monkeypatch):
    api,config=media_api
    source=config.inbox_dir / "invalid.mp4"
    source.write_bytes(b"user-owned invalid media")
    original=digest(source)
    def invalid(_path):
        raise MediaError("Invalid video")
    monkeypatch.setattr(api,"probe_media",invalid)
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            api.import_media(api.ImportMedia(filename=source.name))
        assert error.value.status_code==422
        assert digest(source)==original
        assert list(config.uploads_dir.iterdir())==[]


def test_unsupported_inbox_file_is_preserved(media_api):
    api,config=media_api
    source=config.inbox_dir / "unsupported.txt"
    source.write_bytes(b"not a video, still belongs to the user")
    original=digest(source)
    with pytest.raises(HTTPException) as error:
        api.import_media(api.ImportMedia(filename=source.name))
    assert error.value.status_code==415
    assert digest(source)==original


def test_interrupted_import_only_cleans_its_own_temp_file(media_api,monkeypatch):
    api,config=media_api
    source=config.inbox_dir / "interrupted.webm"
    source.write_bytes(b"untouched original")
    original=digest(source)
    def interrupt(source_file,target,**_kwargs):
        target.write(source_file.read(3))
        raise KeyboardInterrupt("Simulated interrupted copy")
    monkeypatch.setattr(api.shutil,"copyfileobj",interrupt)
    with pytest.raises(KeyboardInterrupt):
        api.import_media(api.ImportMedia(filename=source.name))
    assert digest(source)==original
    assert list(config.uploads_dir.iterdir())==[]


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="FFmpeg unavailable")
def test_valid_import_creates_independent_hash_identical_snapshot(media_api):
    api,config=media_api
    source=config.inbox_dir / "valid.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=s=160x90:r=10",
                    "-t","0.5","-c:v","libx264",str(source)],check=True)
    original=digest(source)
    result=api.import_media(api.ImportMedia(filename=source.name))
    snapshot=Path(api.db.one("SELECT path FROM media WHERE id=?",(result["id"],))["path"])
    assert snapshot.parent==config.uploads_dir
    assert snapshot!=source
    assert digest(source)==digest(snapshot)==original
    source.write_bytes(b"user replaces their inbox file after import")
    assert digest(snapshot)==original


def test_publish_never_overwrites_an_existing_asset(media_api,monkeypatch):
    api,config=media_api
    destination=config.uploads_dir / "collision.mp4"
    destination.write_bytes(b"previous valid asset")
    source=config.inbox_dir / "another.mp4"
    source.write_bytes(b"new source")
    monkeypatch.setattr(api.uuid,"uuid4",lambda:"collision")
    monkeypatch.setattr(api,"probe_media",lambda _path:{"duration":1,"width":1,"height":1,"has_audio":False,"subtitle_streams":[]})
    with pytest.raises(FileExistsError):
        api.import_media(api.ImportMedia(filename=source.name))
    assert destination.read_bytes()==b"previous valid asset"
    assert source.read_bytes()==b"new source"
    assert list(config.uploads_dir.iterdir())==[destination]


def test_failed_upload_cleans_owned_files(media_api,monkeypatch):
    api,config=media_api
    def invalid(_path):
        raise MediaError("Cannot probe video")
    monkeypatch.setattr(api,"probe_media",invalid)
    # No lifespan worker is needed for a media import request.
    client=TestClient(api.app)
    response=client.post("/api/v1/media/upload",files={"file":("bad.mp4",b"bad","video/mp4")})
    assert response.status_code==422
    assert list(config.uploads_dir.iterdir())==[]


def test_registration_failure_preserves_source_and_cleans_snapshot(media_api,monkeypatch):
    api,config=media_api
    source=config.inbox_dir / "database-failure.mp4"
    source.write_bytes(b"user source survives storage failure")
    original=digest(source)
    monkeypatch.setattr(api,"probe_media",lambda _path:{"duration":1,"width":1,"height":1,"has_audio":False,"subtitle_streams":[]})
    def fail(*_args):
        raise OSError("database unavailable")
    monkeypatch.setattr(api.db,"execute",fail)
    with pytest.raises(OSError,match="database unavailable"):
        api.import_media(api.ImportMedia(filename=source.name))
    assert digest(source)==original
    assert not list(config.uploads_dir.iterdir())


def test_insufficient_snapshot_space_is_reported_without_touching_source(media_api,monkeypatch):
    from types import SimpleNamespace
    api,config=media_api
    source=config.inbox_dir / "large.mp4"
    source.write_bytes(b"original must survive low disk space")
    original=digest(source)
    monkeypatch.setattr(api.shutil,"disk_usage",lambda _path:SimpleNamespace(free=0))
    with pytest.raises(HTTPException) as error:
        api.import_media(api.ImportMedia(filename=source.name))
    assert error.value.status_code==507
    assert digest(source)==original
    assert not list(config.uploads_dir.iterdir())
