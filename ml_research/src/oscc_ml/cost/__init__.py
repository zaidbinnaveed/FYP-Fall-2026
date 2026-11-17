"""Cost analysis (FR-7.8): parameters, GFLOPs, latency and peak memory.

Conventions (stated in every evaluation.json):
* GFLOPs: ``torch.utils.flop_counter.FlopCounterMode`` for one 1x3x224x224 forward pass. PyTorch
  counts a multiply-add as 2 FLOPs.
* Latency: batch 1, eval mode, ``torch.inference_mode``, FP32, after warm-up runs; mean and p95
  in milliseconds. GPU timings synchronize the device around each call.
* Peak memory: ``torch.cuda.max_memory_allocated`` during the GPU latency loop (inference) and
  during training (recorded by the trainer).
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.flop_counter import FlopCounterMode

INPUT_SHAPE = (1, 3, 224, 224)


def count_gflops(model: nn.Module) -> float:
    model.eval()
    x = torch.zeros(INPUT_SHAPE)
    with torch.inference_mode(), FlopCounterMode(display=False) as counter:
        model(x)
    return counter.get_total_flops() / 1e9


def measure_latency(
    model: nn.Module, device: torch.device, warmup: int, runs: int
) -> dict[str, Any]:
    model.eval().to(device)
    x = torch.zeros(INPUT_SHAPE, device=device)
    timings: list[float] = []
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    with torch.inference_mode():
        for _ in range(warmup):
            model(x)
        for _ in range(runs):
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            start = time.perf_counter()
            model(x)
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            timings.append((time.perf_counter() - start) * 1000.0)
    arr = np.asarray(timings)
    result: dict[str, Any] = {
        "device": str(device),
        "device_name": (torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu"),
        "mean_ms": float(arr.mean()),
        "p95_ms": float(np.percentile(arr, 95)),
        "warmup": warmup,
        "runs": runs,
        "batch_size": 1,
        "precision": "fp32",
    }
    if device.type == "cpu":
        result["torch_num_threads"] = torch.get_num_threads()
    else:
        result["peak_memory_mb"] = torch.cuda.max_memory_allocated(device) / 2**20
    return result
