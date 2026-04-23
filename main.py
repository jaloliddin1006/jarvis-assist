import os
import json
import wave
import zipfile
import shutil
import asyncio
import tempfile
import threading
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

import requests
import uvicorn
from fastapi import (
    FastAPI, File, UploadFile, Form, Request,
    WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

app = FastAPI(title="Mini Jarvis - STT/TTS")

MODELS_DIR = Path("models")
OUTPUT_DIR = Path("output")
UPLOADS_DIR = Path("uploads")
for d in [MODELS_DIR, OUTPUT_DIR, UPLOADS_DIR]:
    d.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/output", StaticFiles(directory="output"), name="output")
templates = Jinja2Templates(directory="templates")

# ─── Language / Model Configuration ────────────────────────────────────────────
LANGUAGES: Dict[str, Dict] = {
    "en": {
        "name": "English", "flag": "🇺🇸",
        "stt_model": "vosk-model-small-en-us-0.15",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "tts_model": "vosk-model-tts-en-0.15",
        "tts_url": "https://alphacephei.com/vosk/models/vosk-model-tts-en-0.15.zip",
        "tts_speakers": {0: "Default"},
    },
    "ru": {
        "name": "Русский", "flag": "🇷🇺",
        "stt_model": "vosk-model-small-ru-0.22",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
        "tts_model": "vosk-model-tts-ru-0.8-multi",
        "tts_url": "https://alphacephei.com/vosk/models/vosk-model-tts-ru-0.8-multi.zip",
        "tts_speakers": {0: "Aidar", 1: "Baya", 2: "Kseniya", 3: "Xenia", 4: "Eugene"},
    },
    "de": {
        "name": "Deutsch", "flag": "🇩🇪",
        "stt_model": "vosk-model-small-de-0.15",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-small-de-0.15.zip",
        "tts_model": "vosk-model-tts-de-0.6",
        "tts_url": "https://alphacephei.com/vosk/models/vosk-model-tts-de-0.6.zip",
        "tts_speakers": {0: "Default"},
    },
    "fr": {
        "name": "Français", "flag": "🇫🇷",
        "stt_model": "vosk-model-small-fr-0.22",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip",
        "tts_model": None, "tts_url": None, "tts_speakers": {},
    },
    "es": {
        "name": "Español", "flag": "🇪🇸",
        "stt_model": "vosk-model-small-es-0.42",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip",
        "tts_model": None, "tts_url": None, "tts_speakers": {},
    },
    "uz": {
        "name": "O'zbek", "flag": "🇺🇿",
        "stt_model": "vosk-model-uz-0.22",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-uz-0.22.zip",
        "tts_model": None, "tts_url": None, "tts_speakers": {},
    },
    "tr": {
        "name": "Türkçe", "flag": "🇹🇷",
        "stt_model": "vosk-model-small-tr-0.3",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-small-tr-0.3.zip",
        "tts_model": None, "tts_url": None, "tts_speakers": {},
    },
    "zh": {
        "name": "中文", "flag": "🇨🇳",
        "stt_model": "vosk-model-small-cn-0.22",
        "stt_url": "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip",
        "tts_model": None, "tts_url": None, "tts_speakers": {},
    },
}

# ─── In-memory caches ───────────────────────────────────────────────────────────
stt_models: Dict[str, Any] = {}
tts_synths: Dict[str, Any] = {}
download_tasks: Dict[str, Dict] = {}


# ─── Model helpers ──────────────────────────────────────────────────────────────

def _model_path(lang: str, mtype: str) -> Optional[Path]:
    cfg = LANGUAGES.get(lang, {})
    key = f"{mtype}_model"
    name = cfg.get(key)
    return MODELS_DIR / name if name else None


def _download_model(url: str, task_id: str) -> None:
    """Download & extract model zip in a background thread."""
    try:
        download_tasks[task_id].update(status="downloading", progress=0,
                                       message="Connecting…")
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        tmp_zip = MODELS_DIR / f"_tmp_{task_id}.zip"
        downloaded = 0

        with open(tmp_zip, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 80)
                        mb_done = downloaded // 1_048_576
                        mb_total = total // 1_048_576
                        download_tasks[task_id].update(
                            progress=pct,
                            message=f"Downloading… {mb_done} MB / {mb_total} MB"
                        )

        download_tasks[task_id].update(status="extracting", progress=85,
                                       message="Extracting archive…")
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            zf.extractall(MODELS_DIR)
        tmp_zip.unlink(missing_ok=True)

        download_tasks[task_id].update(status="done", progress=100,
                                       message="Model is ready!")
    except Exception as exc:
        download_tasks[task_id].update(status="error", progress=0,
                                       message=str(exc))


def _get_stt_model(lang: str):
    if lang in stt_models:
        return stt_models[lang]
    path = _model_path(lang, "stt")
    if not path or not path.exists():
        raise FileNotFoundError("STT model not downloaded yet.")
    from vosk import Model
    m = Model(str(path))
    stt_models[lang] = m
    return m


def _get_tts_synth(lang: str):
    if lang in tts_synths:
        return tts_synths[lang]
    cfg = LANGUAGES.get(lang, {})
    if not cfg.get("tts_model"):
        raise ValueError("TTS not available for this language.")
    path = _model_path(lang, "tts")
    if not path or not path.exists():
        raise FileNotFoundError("TTS model not downloaded yet.")
    try:
        from vosk_tts import Model as TTSModel, Synth
        m = TTSModel(model_path=str(path))
        s = Synth(m)
        tts_synths[lang] = s
        return s
    except ImportError:
        raise ImportError("vosk-tts not installed. Run: pip install vosk-tts")


# ─── Page routes ────────────────────────────────────────────────────────────────

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("home.html",
                                      {"request": request, "languages": LANGUAGES})


@app.get("/stt")
async def stt_page(request: Request):
    return templates.TemplateResponse("stt.html",
                                      {"request": request, "languages": LANGUAGES})


@app.get("/tts")
async def tts_page(request: Request):
    return templates.TemplateResponse("tts.html",
                                      {"request": request, "languages": LANGUAGES})


# ─── API: model management ──────────────────────────────────────────────────────

@app.get("/api/model/check")
async def check_model(lang: str, type: str):
    cfg = LANGUAGES.get(lang)
    if not cfg:
        raise HTTPException(400, "Unknown language")
    model_name = cfg.get(f"{type}_model")
    if not model_name:
        return {"available": False, "downloaded": False,
                "message": "Not supported for this language"}
    downloaded = (MODELS_DIR / model_name).exists()
    speakers = {}
    if type == "tts" and downloaded:
        speakers = {str(k): v for k, v in cfg.get("tts_speakers", {}).items()}
    return {
        "available": True,
        "downloaded": downloaded,
        "model_name": model_name,
        "speakers": speakers,
    }


@app.post("/api/model/download")
async def start_download(request: Request):
    data = await request.json()
    lang = data.get("lang")
    mtype = data.get("type")
    cfg = LANGUAGES.get(lang)
    if not cfg:
        raise HTTPException(400, "Unknown language")
    url = cfg.get(f"{mtype}_url")
    model_name = cfg.get(f"{mtype}_model")
    if not url or not model_name:
        raise HTTPException(400, "Not supported")
    if (MODELS_DIR / model_name).exists():
        return {"task_id": None, "status": "already_downloaded"}
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {"status": "starting", "progress": 0, "message": "Starting…"}
    threading.Thread(target=_download_model, args=(url, task_id), daemon=True).start()
    return {"task_id": task_id, "status": "started"}


@app.get("/api/model/progress/{task_id}")
async def model_progress(task_id: str):
    return download_tasks.get(task_id, {"status": "not_found"})


# ─── API: STT file upload ───────────────────────────────────────────────────────

@app.post("/api/stt/transcribe")
async def transcribe(file: UploadFile = File(...), lang: str = Form("en")):
    try:
        model = _get_stt_model(lang)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))

    raw_path = UPLOADS_DIR / f"{uuid.uuid4()}_{file.filename}"
    with open(raw_path, "wb") as f:
        f.write(await file.read())

    wav_path = raw_path.with_suffix(".wav")
    converted = False
    try:
        # Try ffmpeg conversion to 16kHz mono PCM
        result = subprocess.run(
            ["ffmpeg", "-i", str(raw_path),
             "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
             str(wav_path), "-y", "-loglevel", "quiet"],
            capture_output=True, timeout=60
        )
        converted = result.returncode == 0 and wav_path.exists()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    process_path = wav_path if converted else raw_path

    try:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model, 16000)
        rec.SetWords(True)
        text_parts = []

        with wave.open(str(process_path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                if not converted:
                    raise HTTPException(
                        400,
                        "Audio must be WAV 16kHz mono 16-bit. "
                        "Install ffmpeg for automatic conversion."
                    )
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    text_parts.append(json.loads(rec.Result()).get("text", ""))
            text_parts.append(json.loads(rec.FinalResult()).get("text", ""))

        return {"text": " ".join(t for t in text_parts if t).strip(),
                "language": lang}
    finally:
        raw_path.unlink(missing_ok=True)
        if converted:
            wav_path.unlink(missing_ok=True)


# ─── API: TTS synthesize ────────────────────────────────────────────────────────

@app.post("/api/tts/synthesize")
async def synthesize(request: Request):
    data = await request.json()
    text = data.get("text", "").strip()
    lang = data.get("lang", "en")
    speaker_id = int(data.get("speaker_id", 0))

    if not text:
        raise HTTPException(400, "Text is required")

    try:
        synth = _get_tts_synth(lang)
    except (FileNotFoundError, ValueError, ImportError) as e:
        raise HTTPException(400, str(e))

    out_file = f"{uuid.uuid4()}.wav"
    out_path = OUTPUT_DIR / out_file
    try:
        synth.synth(text, str(out_path), speaker_id=speaker_id)
        return {"audio_url": f"/output/{out_file}"}
    except Exception as exc:
        raise HTTPException(500, f"TTS error: {exc}")


# ─── WebSocket: real-time microphone STT ────────────────────────────────────────

@app.websocket("/ws/stt/{lang}")
async def ws_stt(websocket: WebSocket, lang: str):
    await websocket.accept()
    try:
        model = _get_stt_model(lang)
    except FileNotFoundError:
        await websocket.send_json({"type": "error", "text": "Model not downloaded"})
        await websocket.close()
        return

    from vosk import KaldiRecognizer
    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(True)
    loop = asyncio.get_event_loop()

    try:
        while True:
            data = await websocket.receive_bytes()
            if not data:
                continue
            accepted = await loop.run_in_executor(None, rec.AcceptWaveform, data)
            if accepted:
                result = json.loads(rec.Result())
                await websocket.send_json({"type": "final",
                                           "text": result.get("text", "")})
            else:
                partial = json.loads(rec.PartialResult())
                await websocket.send_json({"type": "partial",
                                           "text": partial.get("partial", "")})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
