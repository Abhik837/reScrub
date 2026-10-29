# Worker image for NVIDIA GPUs (CUDA): analysis on a GPU server or with docker-compose.local.gpu.yml,
# and model training (docs/TRAINING.md). The API uses the smaller Dockerfile.api.
FROM pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    MODELS_DIR=/models \
    YOLO_CONFIG_DIR=/models/ultralytics \
    XDG_CACHE_HOME=/models/cache \
    HF_HOME=/models/hf
# Large downloads (PyTorch, OpenCV) stall briefly on slow networks and under WSL 2; pip's default
# 15 s timeout would abort the whole step.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates ffmpeg git libgl1 libglib2.0-0 wget unzip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# rtmlib pulls in the CPU-only onnxruntime, which shadows onnxruntime-gpu and puts the hand model on the
# CPU. Remove it and reinstall the GPU build so CUDAExecutionProvider is available. The last check makes
# sure that build is for the same CUDA major version as torch; otherwise it fails to load at runtime
# (missing libcublasLt.so.N) and the hand model silently falls back to the CPU.
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y onnxruntime \
 && pip install --no-cache-dir --no-deps --force-reinstall "$(grep -E '^onnxruntime-gpu' requirements.txt | cut -d';' -f1 | tr -d ' ')" \
 && python -c "import onnxruntime as o; p = o.get_available_providers(); print(p); assert 'CUDAExecutionProvider' in p" \
 && python -c "import os, re, torch, onnxruntime as o; lib = os.path.join(os.path.dirname(o.__file__), 'capi', 'libonnxruntime_providers_cuda.so'); m = re.search(rb'libcublasLt\.so\.(\d+)', open(lib, 'rb').read()); built = m.group(1).decode() if m else '?'; print('onnxruntime CUDA', built, '/ torch CUDA', torch.version.cuda); assert built == torch.version.cuda.split('.')[0], 'onnxruntime-gpu is built for another CUDA than torch: change its pin in requirements.txt'"

COPY . .
# Bake every model into the image so containers start without downloads.
RUN python -m rescrub.download_models

RUN useradd --create-home --uid 1000 app && mkdir -p /app/data /models/trained && chown -R app /app /models
USER app

EXPOSE 8000
CMD ["uvicorn", "rescrub.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
