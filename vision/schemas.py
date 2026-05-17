from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class VehicleClass(str, Enum):
    car = "car"
    truck = "truck"
    motorcycle = "motorcycle"
    bus = "bus"
    pedestrian = "pedestrian"
    cyclist = "cyclist"
    unknown = "unknown"


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float
    confidence: float = Field(ge=0.0, le=1.0)


class VehicleDetection(BaseModel):
    track_id: str
    vehicle_class: VehicleClass
    bounding_box: BoundingBox
    frame_id: str
    timestamp_ms: int
    metadata: dict = Field(default_factory=dict)


class InferenceFrame(BaseModel):
    frame_id: str
    camera_id: str
    timestamp_ms: int
    width: int
    height: int
    source_type: str = "synthetic"
    detections: list[VehicleDetection] = Field(default_factory=list)
    inference_latency_ms: float | None = None
