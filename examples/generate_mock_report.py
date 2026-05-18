from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from analytics.flow import FlowWindow
from analytics.metrics import AnalyticsMetrics
from vision.adapters import MockDetectionAdapter
from vision.schemas import InferenceFrame


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic mock inference evidence.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("examples/mock_inference_report.json"),
        help="Path for the generated JSON report.",
    )
    args = parser.parse_args()
    report = build_report()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_report() -> dict[str, object]:
    adapter = MockDetectionAdapter(seed=7)
    flow = FlowWindow(camera_id="cam-demo", window_size=4, congestion_threshold=3)
    metrics = AnalyticsMetrics()
    class_counts: Counter[str] = Counter()
    per_frame_counts: list[int] = []

    for frame in _fixed_frames():
        inferred = adapter.infer(frame)
        flow.push(inferred)
        detection_count = len(inferred.detections)
        per_frame_counts.append(detection_count)
        metrics.frames_processed += 1
        metrics.total_detections += detection_count
        metrics.congestion_events += int(flow.is_congested)
        for detection in inferred.detections:
            class_counts[detection.vehicle_class.value] += 1

    return {
        "source": "synthetic-fixed-frames",
        "adapter": "MockDetectionAdapter",
        "safety_boundary": "synthetic observability evidence only; no automated enforcement",
        "frames_processed": metrics.frames_processed,
        "total_detections": metrics.total_detections,
        "congestion_windows": metrics.congestion_events,
        "per_frame_detection_counts": per_frame_counts,
        "class_counts": dict(sorted(class_counts.items())),
        "unsupported_claims": [
            "real camera accuracy",
            "Jetson hardware latency",
            "automated enforcement readiness",
        ],
    }


def _fixed_frames() -> list[InferenceFrame]:
    return [
        InferenceFrame(
            frame_id=f"frame-{index:03d}",
            camera_id="cam-demo",
            timestamp_ms=1_800_000_000_000 + index * 100,
            width=1280,
            height=720,
        )
        for index in range(8)
    ]


if __name__ == "__main__":
    main()
