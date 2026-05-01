import os
import uuid
import asyncio
from fastapi import FastAPI, UploadFile, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from ffmpeg_progress_yield import FfmpegProgress

app = FastAPI(title="StreamForge Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE_PATH = "./storage"
os.makedirs(STORAGE_PATH, exist_ok=True)
app.mount("/storage", StaticFiles(directory=STORAGE_PATH), name="storage")

tasks_status = {}
conversion_semaphore = asyncio.Semaphore(2)

async def generate_hls_stream(task_id: str, input_path: str, output_folder: str):
    async with conversion_semaphore:
        os.makedirs(output_folder, exist_ok=True)
        
        qualities = {
            "360p": {"res": "640x360", "bitrate": "800k"},
            "720p": {"res": "1280x720", "bitrate": "2800k"},
            "1080p": {"res": "1920x1080", "bitrate": "5000k"}
        }
        

        master_playlist = "#EXTM3U\n#EXT-X-VERSION:3\n"

        for name, config in qualities.items():
            q_folder = os.path.join(output_folder, name)
            os.makedirs(q_folder, exist_ok=True)
            
            command = [
                "ffmpeg", "-i", input_path,
                "-vf", f"scale={config['res']}",
                "-codec:v", "libx264", "-crf", "20", "-b:v", config['bitrate'],
                "-codec:a", "aac", "-b:a", "128k",
                "-hls_time", "6", "-hls_list_size", "0",
                "-f", "hls", os.path.join(q_folder, "index.m3u8")
            ]

            ff = FfmpegProgress(command)
            for progress in ff.run_command_with_progress():
                tasks_status[task_id]["progress"] = round(progress, 2)

            bandwidth = int(config['bitrate'].replace('k', '000'))
            master_playlist += f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={config['res']}\n"
            master_playlist += f"{name}/index.m3u8\n"

        with open(os.path.join(output_folder, "master.m3u8"), "w") as f:
            f.write(master_playlist)

        tasks_status[task_id]["status"] = "completed"
        tasks_status[task_id]["progress"] = 100
        
        if os.path.exists(input_path):
            os.remove(input_path)

@app.post("/upload")
async def upload_video(file: UploadFile, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    input_path = f"{STORAGE_PATH}/{task_id}_{file.filename}"
    output_folder = f"{STORAGE_PATH}/{task_id}_stream"

    with open(input_path, "wb") as f:
        f.write(await file.read())

    tasks_status[task_id] = {"status": "processing", "progress": 0}
    background_tasks.add_task(generate_hls_stream, task_id, input_path, output_folder)

    return {"task_id": task_id}

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    if task_id not in tasks_status:
        raise HTTPException(status_code=404)
    
    data = tasks_status[task_id]
    if data["status"] == "completed":
        data["stream_url"] = f"http://127.0.0.1:8000/storage/{task_id}_stream/master.m3u8"
    
    return data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
    



