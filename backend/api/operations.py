from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.deps import get_config, get_db
from backend.models import (
    ExportEstimateRequest, ExportEstimateResponse, ExportRequest, ExportResponse, ExportStatusResponse,
    S3SyncRequest, S3SyncResponse, S3ObjectResponse,
    RecoverVerifyRequest, RecoverVerifyResponse, RecoverFromS3Request, RecoverFromExportRequest, RecoverResponse,
    SnapshotCreateRequest, SnapshotResponse, SnapshotRestoreRequest,
    ImportPreviewRequest, ImportPreviewResponse, ImportExecuteRequest, ImportExecuteResponse,
    S3ConfigRequest, S3TestConnectionRequest, S3TestConnectionResponse,
    S3CreateBucketRequest, S3CreateBucketResponse,
    S3SaveConfigRequest, S3SaveConfigResponse,
)


router = APIRouter(tags=["operations"])


@router.post("/export/estimate", response_model=ExportEstimateResponse)
async def estimate_export(request: ExportEstimateRequest) -> ExportEstimateResponse:
    from backend.services.estimation import estimate_export_size
    db = get_db()
    config = get_config()
    return await estimate_export_size(db, config, request.dataset_id, request.type, request.export_mode)


@router.post("/export/full", response_model=ExportResponse)
async def export_full(request: ExportRequest) -> ExportResponse:
    from backend.services.export_service import run_full_export
    db = get_db()
    config = get_config()
    export_id = await run_full_export(db, config, request.dataset_id, request.push_s3, request.formats, request.export_mode, request.verify_images)
    return ExportResponse(export_id=export_id, status="started", message="Full export started")


@router.post("/export/incremental", response_model=ExportResponse)
async def export_incremental(request: ExportRequest) -> ExportResponse:
    from backend.services.export_service import run_incremental_export
    db = get_db()
    config = get_config()
    export_id = await run_incremental_export(db, config, request.dataset_id, request.push_s3, request.formats, request.export_mode, request.verify_images)
    return ExportResponse(export_id=export_id, status="started", message="Incremental export started")


@router.get("/export/status/{export_id}", response_model=ExportStatusResponse)
async def export_status(export_id: str) -> ExportStatusResponse:
    from backend.services.export_service import get_export_status
    return await get_export_status(export_id)


@router.post("/s3/sync", response_model=S3SyncResponse)
async def s3_sync(request: S3SyncRequest) -> S3SyncResponse:
    from backend.services.s3_service import S3Service
    config = get_config()
    db = get_db()
    s3_service = S3Service(config, db)
    result = await s3_service.sync(request.fetch, request.push)
    return S3SyncResponse(**result)


@router.get("/s3/objects", response_model=list[S3ObjectResponse])
async def list_s3_objects(dataset_id: int) -> list[S3ObjectResponse]:
    from backend.services.s3_service import S3Service
    config = get_config()
    db = get_db()
    s3_service = S3Service(config, db)
    return await s3_service.list_objects(dataset_id)


@router.post("/recover/verify", response_model=RecoverVerifyResponse)
async def verify_export(request: RecoverVerifyRequest) -> RecoverVerifyResponse:
    from backend.recovery.integrity import verify_export
    return await verify_export(request.export_path)


@router.post("/recover/from-s3", response_model=RecoverResponse)
async def recover_from_s3(request: RecoverFromS3Request) -> RecoverResponse:
    from backend.recovery.s3_recovery import recover_from_s3
    config = get_config()
    return await recover_from_s3(config, request.dataset_name, request.bucket, request.target_dir, request.region)


@router.post("/recover/from-export", response_model=RecoverResponse)
async def recover_from_export(request: RecoverFromExportRequest) -> RecoverResponse:
    from backend.recovery.recovery_engine import recover_from_export
    config = get_config()
    return await recover_from_export(config, request.export_path, request.target_dir)


@router.post("/recover/verify-recovery")
async def verify_recovery(target_dir: str) -> dict[str, Any]:
    from backend.recovery.integrity import verify_recovery
    return await verify_recovery(target_dir)


@router.post("/snapshots", response_model=SnapshotResponse)
async def create_snapshot_endpoint(request: SnapshotCreateRequest) -> SnapshotResponse:
    from backend.database import create_snapshot
    db = get_db()
    config = get_config()
    from pathlib import Path
    snapshot_path = await create_snapshot(db, request.dataset_id, Path(config.snapshot.path), request.trigger)
    snap = await db.fetchone(
        "SELECT * FROM snapshots WHERE snapshot_path = ? AND dataset_id = ?",
        (str(snapshot_path), request.dataset_id)
    )
    return SnapshotResponse(**snap)


@router.get("/snapshots", response_model=list[SnapshotResponse])
async def list_snapshots(dataset_id: int) -> list[SnapshotResponse]:
    db = get_db()
    snaps = await db.fetchall(
        "SELECT * FROM snapshots WHERE dataset_id = ? ORDER BY created_at DESC",
        (dataset_id,)
    )
    return [SnapshotResponse(**s) for s in snaps]


@router.post("/snapshots/restore")
async def restore_snapshot_endpoint(request: SnapshotRestoreRequest) -> dict[str, str]:
    from backend.database import restore_snapshot
    db = get_db()
    await restore_snapshot(db, request.dataset_id, request.snapshot_id)
    return {"status": "restored"}


@router.post("/import/preview", response_model=ImportPreviewResponse)
async def preview_import(request: ImportPreviewRequest) -> ImportPreviewResponse:
    from backend.services.import_service import preview_import
    return await preview_import(request.format, request.file_content)


@router.post("/import/execute", response_model=ImportExecuteResponse)
async def execute_import(request: ImportExecuteRequest) -> ImportExecuteResponse:
    from backend.services.import_service import execute_import
    db = get_db()
    config = get_config()
    return await execute_import(db, config, request.dataset_id, request.format, request.file_content, request.field_mapping)


# S3 Configuration Endpoints
@router.post("/s3/test-connection", response_model=S3TestConnectionResponse)
async def test_s3_connection(request: S3TestConnectionRequest) -> S3TestConnectionResponse:
    from backend.services.s3_service import S3Service
    config = get_config()
    db = get_db()
    
    # Create a temporary config with the provided credentials
    from backend.config import AppConfig, S3Config
    test_config = config.model_copy()
    test_config.s3 = S3Config(**request.config.model_dump())
    
    s3_service = S3Service(test_config, db)
    try:
        # Try to list objects to test connection
        await s3_service.list_objects(1)
        return S3TestConnectionResponse(success=True, message="Connection successful!")
    except Exception as e:
        return S3TestConnectionResponse(success=False, message=f"Connection failed: {str(e)}")


@router.post("/s3/create-bucket", response_model=S3CreateBucketResponse)
async def create_s3_bucket(request: S3CreateBucketRequest) -> S3CreateBucketResponse:
    import boto3
    from botocore.config import Config as BotoConfig
    
    cfg = request.config
    if not cfg.bucket:
        return S3CreateBucketResponse(success=False, message="Bucket name is required")
    
    try:
        session = boto3.Session()
        boto_config = BotoConfig(
            max_pool_connections=10,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        
        s3 = session.client(
            "s3",
            region_name=cfg.region,
            endpoint_url=cfg.endpoint_url or None,
            aws_access_key_id=cfg.access_key_id or None,
            aws_secret_access_key=cfg.secret_access_key or None,
            config=boto_config,
        )
        
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=cfg.bucket)
            return S3CreateBucketResponse(success=True, message=f"Bucket '{cfg.bucket}' already exists")
        except Exception:
            pass
        
        # Create bucket
        if cfg.region == "us-east-1":
            s3.create_bucket(Bucket=cfg.bucket)
        else:
            s3.create_bucket(
                Bucket=cfg.bucket,
                CreateBucketConfiguration={"LocationConstraint": cfg.region}
            )
        
        return S3CreateBucketResponse(success=True, message=f"Bucket '{cfg.bucket}' created successfully!")
    except Exception as e:
        return S3CreateBucketResponse(success=False, message=f"Failed to create bucket: {str(e)}")


@router.post("/s3/save-config", response_model=S3SaveConfigResponse)
async def save_s3_config(request: S3SaveConfigRequest) -> S3SaveConfigResponse:
    import yaml
    from pathlib import Path
    from backend.config import S3Config
    from backend.deps import set_config
    config = get_config()

    # Update the config with new S3 settings.
    new_s3_config = S3Config(**request.config.model_dump())

    # Apply to the LIVE in-memory config so subsequent operations (e.g. S3 push
    # right after export) use these credentials without a restart.
    config.s3 = new_s3_config
    set_config(config)

    # Save a redacted copy to the YAML file (secrets are not written to disk).
    updated_config = config.model_copy()
    updated_config.s3 = new_s3_config

    config_path = Path("config/dataset_config.yaml")

    config_dict = updated_config.model_dump(mode="json")
    if config_dict.get("s3"):
        config_dict["s3"]["access_key_id"] = ""
        config_dict["s3"]["secret_access_key"] = ""
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

    # Persist credentials to .env so they survive a server restart. Secrets are
    # loaded back via pydantic-settings (Settings) in backend/config.load_config.
    _write_s3_env(
        access_key_id=request.config.access_key_id,
        secret_access_key=request.config.secret_access_key,
        endpoint_url=request.config.endpoint_url,
    )

    return S3SaveConfigResponse(
        success=True,
        message="S3 configuration saved and applied.",
        config=request.config
    )


def _write_s3_env(access_key_id: str | None, secret_access_key: str | None, endpoint_url: str | None) -> None:
    """Merge S3 credentials into the project .env file (created if missing)."""
    from pathlib import Path
    env_path = Path(".env")
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updates = {
        "s3_access_key_id": access_key_id,
        "s3_secret_access_key": secret_access_key,
        "s3_endpoint_url": endpoint_url,
    }

    def _upsert(rows: list[str], key: str, value: str | None) -> list[str]:
        prefix = key + "="
        out = [r for r in rows if not r.strip().startswith(prefix)]
        if value is not None and value.strip() != "":
            out.append(f"{prefix}{value.strip()}")
        return out

    for key, value in updates.items():
        lines = _upsert(lines, key, value)

    env_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")