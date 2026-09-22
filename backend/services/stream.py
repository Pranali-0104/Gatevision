import threading
import time
import cv2
import base64
import re
import os
import numpy as np
from datetime import datetime
import torch
from ultralytics import YOLO

from services.detection import (
    get_detector,
    load_selected_model,
    detect_plate_in_roi,
    read_plate_ocr,
    load_settings
)
from services.matcher import push_driver_event, push_plate_event

stream_threads = {}
stop_events = {}
latest_results = {}
latest_results_lock = threading.Lock()

vehicle_model = None
vehicle_model_lock = threading.Lock()

def get_vehicle_model():
    global vehicle_model
    with vehicle_model_lock:
        if vehicle_model is not None:
            return vehicle_model
        model_name = "yolov8s.pt" if torch.cuda.is_available() else "yolov8n.pt"
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(base_dir, model_name)
        if os.path.exists(model_path):
            vehicle_model = YOLO(model_path)
        else:
            vehicle_model = YOLO(model_name)
        return vehicle_model

class ModernFaceDetector:
    def __init__(self):
        self.net = None
        self.use_cascade = True
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        weights_dir = os.path.join(base_dir, "weights")
        self.model_path = os.path.join(weights_dir, "yunet.onnx")
        
        if os.path.exists(self.model_path):
            try:
                self.use_cascade = False
            except Exception:
                pass

    def detect(self, image):
        if image is None or image.size == 0:
            return []
        h, w = image.shape[:2]
        if not self.use_cascade:
            try:
                detector = cv2.FaceDetectorYN.create(self.model_path, "", (w, h))
                _, faces = detector.detect(image)
                if faces is not None:
                    return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[14] if len(f)>14 else 0.9)) for f in faces]
            except Exception:
                pass

        try:
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            face_cascade = cv2.CascadeClassifier(cascade_path)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            return [(fx, fy, fw, fh, 0.80) for (fx, fy, fw, fh) in faces]
        except Exception:
            return []

class ThreadedCamera:
    def __init__(self, src):
        self.cap = cv2.VideoCapture(src)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.ret = False
        self.frame = None
        self.running = True
        self.lock = threading.Lock()
        if self.cap.isOpened():
            self.ret, self.frame = self.cap.read()
            self.thread = threading.Thread(target=self._update, daemon=True)
            self.thread.start()

    def _update(self):
        while self.running:
            if self.cap.isOpened():
                ret, frame = self.cap.read()
                with self.lock:
                    self.ret = ret
                    self.frame = frame
            else:
                time.sleep(0.1)

    def read(self):
        with self.lock:
            if self.frame is not None:
                return self.ret, self.frame.copy()
            return self.ret, None
            
    def isOpened(self): return self.cap.isOpened()
    def get(self, propId): return self.cap.get(propId)
    def set(self, propId, value): return self.cap.set(propId, value)
    def release(self):
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)
        self.cap.release()

def encode_live_preview(frame, settings, tracked_vehicles=None):
    max_w = settings.get("live_preview_max_width", 960)
    h, w = frame.shape[:2]
    preview = frame
    sx = sy = 1.0
    if w > max_w:
        sx = max_w / float(w)
        sy = sx
        preview = cv2.resize(frame, (max_w, int(h * sx)), interpolation=cv2.INTER_AREA)

    if tracked_vehicles:
        for track_id, (vx1, vy1, vx2, vy2), _ in tracked_vehicles:
            px1, py1 = int(vx1 * sx), int(vy1 * sy)
            px2, py2 = int(vx2 * sx), int(vy2 * sy)
            cv2.rectangle(preview, (px1, py1), (px2, py2), (0, 255, 0), 2)
            cv2.putText(preview, f"ID {track_id}", (px1, max(10, py1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    jpeg_quality = settings.get("live_preview_jpeg_quality", 60)
    ok, full_buffer = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if not ok: return ""
    return base64.b64encode(full_buffer).decode("utf-8")

def process_stream(source, camera_id, gate_id, lane, direction, role, mode, stream_type, is_upload):
    settings = load_settings()
    cap = None
    
    source_val = source
    if isinstance(source_val, str) and not source_val.isdigit() and "subtype=" in source_val:
        source_val = source_val.replace("subtype=0", "subtype=1") if stream_type == "sub" else source_val.replace("subtype=1", "subtype=0")
        
    is_local_file = isinstance(source_val, str) and not source_val.startswith(("http", "rtsp")) and os.path.isfile(source_val)
    
    try:
        if not is_local_file:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000"
            cap = ThreadedCamera(source_val)
        else:
            os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
            cap = cv2.VideoCapture(source_val)
    except Exception as e:
        print(f"[ANPR Stream] Failed to open {camera_id}: {e}")
        return

    if not cap.isOpened():
        print(f"[ANPR Stream] Could not open {camera_id}")
        return

    print(f"[ANPR Stream] Connected to {camera_id} | Role: {role} | Gate: {gate_id} | Lane: {lane}")
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    preview_interval = max(1, int(round(fps / settings.get("live_preview_fps", 5))))
    detection_interval = max(1, int(round(fps / settings.get("live_detection_fps", 15))))
    
    frame_count = 0
    active_tracks = {} # Keep track of vehicles to avoid multiple triggers
    
    vehicle_tracker = get_vehicle_model() if role == "PLATE" else None
    plate_model = get_detector(load_selected_model()) if role == "PLATE" else None
    face_detector = ModernFaceDetector() if role == "DRIVER" else None

    # Using Haar cascade for person detection in driver pipeline as fallback if YOLO is overkill
    # But YOLO is better. We'll use vehicle_tracker for PERSON class (cls 0) for driver role
    person_tracker = get_vehicle_model() if role == "DRIVER" else None

    while camera_id in stop_events and not stop_events[camera_id].is_set():
        if is_local_file and fps > 0:
            time.sleep(1.0 / fps)
            
        ret, frame = cap.read()
        if not ret or frame is None:
            if is_upload:
                break
            time.sleep(1)
            continue
            
        frame_count += 1
        now = time.monotonic()
        
        tracked_ui_boxes = []

        if frame_count % detection_interval == 0:
            # 1. PLATE PIPELINE
            if role == "PLATE":
                try:
                    results = vehicle_tracker.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False, imgsz=640)
                    boxes = results[0].boxes
                    if boxes is not None:
                        for box in boxes:
                            if box.id is not None and int(box.cls[0]) in [2, 3, 5, 7]: # Car, Motorcycle, Bus, Truck
                                conf = float(box.conf[0])
                                track_id = int(box.id[0])
                                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                                tracked_ui_boxes.append((track_id, (x1, y1, x2, y2), conf))
                                
                                if track_id not in active_tracks:
                                    active_tracks[track_id] = {"triggered": False, "frames": 0}
                                
                                active_tracks[track_id]["frames"] += 1
                                
                                # Trigger logic: Continuously attempt OCR until we get a successful read.
                                if not active_tracks[track_id]["triggered"]:
                                    # Execute plate detection & OCR on this frame
                                    pad_x, pad_y = int((x2 - x1)*0.15), int((y2 - y1)*0.15)
                                    vx1, vy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
                                    vx2, vy2 = min(frame.shape[1], x2 + pad_x), min(frame.shape[0], y2 + pad_y)
                                    v_crop = frame[vy1:vy2, vx1:vx2]
                                    
                                    p_crop, _, _ = detect_plate_in_roi(v_crop, plate_model, settings)
                                    if p_crop is not None:
                                        history, early_exit, early_data = read_plate_ocr(p_crop, settings)
                                        if early_data:
                                            # We got a successful read! Stop processing this track_id.
                                            active_tracks[track_id]["triggered"] = True
                                            print(f"[PLATE Pipeline] Successful capture for Track ID {track_id}")
                                            
                                            # Update live preview data
                                            with latest_results_lock:
                                                if camera_id not in latest_results:
                                                    latest_results[camera_id] = {}
                                                latest_results[camera_id].update({
                                                    "plate": early_data["text"],
                                                    "confidence": int(early_data["conf"] * 100),
                                                    "gate_id": gate_id,
                                                    "lane": lane,
                                                    "new_detection": True
                                                })
                                                
                                            push_plate_event(
                                                timestamp=now,
                                                camera_id=camera_id,
                                                gate_id=gate_id,
                                                lane=lane,
                                                direction=direction,
                                                plate_text=early_data["text"],
                                                confidence=int(early_data["conf"] * 100),
                                                vehicle_crop=v_crop,
                                                plate_crop=p_crop
                                            )

                except Exception as e:
                    print(f"[PLATE Pipeline Error] {e}")

            # 2. DRIVER PIPELINE
            elif role == "DRIVER":
                # Temporarily disabled per user request to improve performance and stability
                pass

        if frame_count % preview_interval == 0:
            img_str = encode_live_preview(frame, settings, tracked_ui_boxes)
            with latest_results_lock:
                if camera_id not in latest_results:
                    latest_results[camera_id] = {}
                
                # Keep existing plate data if present, only update image/status
                latest_results[camera_id].update({
                    "image": img_str,
                    "status": "running",
                    "mode": mode,
                    "camera": camera_id
                })

    if cap is not None:
        try: cap.release()
        except: pass

def start_stream(source, camera_id, gate_id="GATE_1", lane="ENTRY", direction="IN", role="PLATE", mode="detection", stream_type="main", is_upload=False):
    if camera_id in stream_threads and stream_threads[camera_id].is_alive():
        return False
    stop_events[camera_id] = threading.Event()
    thread = threading.Thread(
        target=process_stream,
        args=(source, camera_id, gate_id, lane, direction, role, mode, stream_type, is_upload),
        daemon=True
    )
    stream_threads[camera_id] = thread
    thread.start()
    return True

def stop_stream(camera_id=None):
    if camera_id is None:
        for cid, event in stop_events.items(): event.set()
        for cid, thread in stream_threads.items(): thread.join(timeout=2)
        stream_threads.clear()
        stop_events.clear()
        with latest_results_lock: latest_results.clear()
    else:
        if camera_id in stop_events: stop_events[camera_id].set()
        if camera_id in stream_threads:
            stream_threads[camera_id].join(timeout=2)
            del stream_threads[camera_id]
            del stop_events[camera_id]
        with latest_results_lock:
            if camera_id in latest_results: del latest_results[camera_id]
    return True

def get_latest_result():
    with latest_results_lock:
        # Create a deep-ish copy to return
        result = {}
        for k, v in latest_results.items():
            result[k] = dict(v)
            # Clear new_detection so it only fires once
            if "new_detection" in latest_results[k]:
                del latest_results[k]["new_detection"]
        return result
