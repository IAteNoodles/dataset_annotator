from __future__ import annotations

import json
from typing import Any
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel


class WSMessage(BaseModel):
    type: str
    payload: dict[str, Any]


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = defaultdict(list)
        self.user_data: dict[WebSocket, dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket, dataset_id: int):
        await websocket.accept()
        self.active_connections[dataset_id].append(websocket)
        self.user_data[websocket] = {"dataset_id": dataset_id}

    def disconnect(self, websocket: WebSocket):
        data = self.user_data.get(websocket, {})
        dataset_id = data.get("dataset_id")
        if dataset_id and dataset_id in self.active_connections:
            if websocket in self.active_connections[dataset_id]:
                self.active_connections[dataset_id].remove(websocket)
        if websocket in self.user_data:
            del self.user_data[websocket]

    async def send_personal_message(self, message: dict[str, Any], websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception:
            pass

    async def broadcast(self, dataset_id: int, message: dict[str, Any]):
        if dataset_id not in self.active_connections:
            return
        disconnected = []
        for connection in self.active_connections[dataset_id]:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_to_all(self, message: dict[str, Any]):
        for dataset_id in self.active_connections:
            await self.broadcast(dataset_id, message)


manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket, dataset_id: int):
    await manager.connect(websocket, dataset_id)
    try:
        while True:
            data = await websocket.receive_json()
            message = WSMessage(**data)

            if message.type == "ping":
                await manager.send_personal_message({"type": "pong"}, websocket)
            elif message.type == "subscribe":
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


async def broadcast_annotation_created(dataset_id: int, annotation: dict[str, Any]):
    await manager.broadcast(dataset_id, {
        "type": "annotation_created",
        "annotation": annotation,
    })


async def broadcast_annotation_updated(dataset_id: int, annotation: dict[str, Any]):
    await manager.broadcast(dataset_id, {
        "type": "annotation_updated",
        "annotation": annotation,
    })


async def broadcast_annotation_deleted(dataset_id: int, annotation_id: int):
    await manager.broadcast(dataset_id, {
        "type": "annotation_deleted",
        "annotation_id": annotation_id,
    })


async def broadcast_annotation_moved(dataset_id: int, annotation_id: int, geometry: dict[str, Any]):
    await manager.broadcast(dataset_id, {
        "type": "annotation_moved",
        "annotation_id": annotation_id,
        "geometry": geometry,
    })


async def broadcast_field_updated(dataset_id: int, annotation_id: int, field_name: str, field_value: str):
    await manager.broadcast(dataset_id, {
        "type": "field_updated",
        "annotation_id": annotation_id,
        "field_name": field_name,
        "field_value": field_value,
    })


async def broadcast_suggestions_updated(dataset_id: int, field_name: str, suggestions: list[str]):
    await manager.broadcast(dataset_id, {
        "type": "suggestions_updated",
        "field_name": field_name,
        "suggestions": suggestions,
    })


async def broadcast_export_progress(export_id: str, progress: float, step: str, processed: int, total: int):
    await manager.broadcast_to_all({
        "type": "export_progress",
        "export_id": export_id,
        "progress": progress,
        "current_step": step,
        "records_processed": processed,
        "total_records": total,
    })


async def broadcast_s3_sync_progress(dataset_id: int, operation: str, progress: float, message: str):
    await manager.broadcast(dataset_id, {
        "type": "s3_sync_progress",
        "operation": operation,
        "progress": progress,
        "message": message,
    })