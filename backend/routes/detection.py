from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
import numpy as np
import cv2
import base64
from sqlalchemy.orm import Session

from database import SessionLocal
from auth import require_permissions
import crud
from services.detection import detect_plate
from services.utils import get_category
from routes.models import load_selected_model

router = APIRouter(prefix="/detect", tags=["Detection"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
async def detect_vehicle(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("detection:run")),
):

    # -------- READ IMAGE --------
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    # -------- DETECTION --------
    plate_text, processed_image, crop_path, detector_used, raw_text, corrected, conf_value, final_crop = detect_plate(image)
    hotlist_entry = get_category(db, plate_text)
    
    category_name = "Unknown"
    category_code = "unknown"
    category_color = "gray"
    
    if hotlist_entry:
        category_name = hotlist_entry["category_name"]
        category_code = hotlist_entry["category_code"]
        category_color = hotlist_entry["category_color"]

    # -------- SAVE RECORD --------
    record = crud.create_record(db, {
        "plate": plate_text,
        "raw_text": raw_text,
        "confidence": int(conf_value * 100),
        "site": "Goa Airport",
        "camera": "ENTRY_1",
        "category": category_name, # keep for backwards compat
        "category_name": category_name,
        "category_code": category_code,
        "category_color": category_color,
        "plate_image_url": None, # will update after saving file
        "model_used": load_selected_model(),
        "detector_used": detector_used,
        "image_storage_type": "filesystem" if final_crop is not None else None
    })

    # -------- SAVE CROP TO FILESYSTEM & UPDATE URL --------
    if final_crop is not None:
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dt = record.time # Use detection timestamp
        storage_dir = os.path.join(base_dir, "storage", f"{dt.year}", f"{dt.month:02d}", f"{dt.day:02d}")
        os.makedirs(storage_dir, exist_ok=True)
        file_name = f"plate_{record.id}.jpg"
        file_path = os.path.join(storage_dir, file_name)
        cv2.imwrite(file_path, final_crop)
        
        # Store relative path in DB
        relative_url = f"storage/{dt.year}/{dt.month:02d}/{dt.day:02d}/{file_name}"
        record.plate_image_url = relative_url
        db.commit()
        db.refresh(record)

    # -------- ENCODE CROP IMAGE FOR LIVE DISPLAY (Phase A) --------
    if final_crop is not None:
        _, crop_buffer = cv2.imencode('.jpg', final_crop)
        crop_str = base64.b64encode(crop_buffer).decode('utf-8')
        api_plate_image_url = f"data:image/jpeg;base64,{crop_str}"
    else:
        api_plate_image_url = None

    # -------- ENCODE FULL IMAGE FOR LIVE PANEL --------
    _, full_buffer = cv2.imencode('.jpg', processed_image)
    img_str = base64.b64encode(full_buffer).decode('utf-8')

    return {
        "plate": plate_text,
        "raw_text": raw_text,
        "corrected": corrected,
        "crop_image_path": crop_path,
        "model_used": load_selected_model(),
        "detector_used": detector_used,
        "confidence": float(conf_value),
        "category": category_name,
        "category_name": category_name,
        "category_code": category_code,
        "category_color": category_color,
        "record_id": record.id,
        "image": img_str,
        "plate_image_url": api_plate_image_url,
        "site": record.site,
        "camera": record.camera,
        "time": record.time
    }


@router.post("/video")
async def detect_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(require_permissions("detection:run")),
):
    import os
    import time
    import tempfile
    from pathlib import Path
    
    # Import necessary pipeline functions
    from services.stream import get_vehicle_model
    from services.detection import (
        get_detector,
        load_settings,
        detect_plate_in_roi,
        calculate_perspective_score,
        calculate_pre_ocr_score,
        get_ocr_variants,
        normalize_plate_string,
        weighted_voting,
        post_process_indian_plate,
        are_crops_similar,
        CLASSIC_PLATE_RE,
        BH_PLATE_RE,
        load_selected_model
    )
    
    # 1. Save uploaded video to temp file
    suffix = Path(file.filename).suffix if file.filename else ".mp4"
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dir = os.path.join(base_dir, "storage")
    os.makedirs(temp_dir, exist_ok=True)
    
    fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=temp_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            contents = await file.read()
            f.write(contents)
            
        # 2. Open video capture
        cap = cv2.VideoCapture(temp_path)
        if not cap.isOpened():
            raise HTTPException(status_code=400, detail="Could not open video file")
            
        # Calculate adaptive frame skip based on video FPS
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or np.isnan(fps):
            fps = 30.0
        frame_skip = max(1, int(round(fps / 6.0)))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        vehicle_tracker = get_vehicle_model()
        plate_model = get_detector(load_selected_model())
        settings = load_settings()
        lane_id = settings.get("lane_id", "LANE_1")
        
        local_cache = {}
        completed_tracks = set()
        detected_records = []
        frame_count = 0
        total_ocr_executions = 0
        total_cache_hits = 0
        
        start_time_overall = time.time()
        
        def commit_track(t_id, track_data):
            # Helper to finalize and commit a track
            nonlocal db
            if not track_data.get("best_text") or track_data["state"] in ("COMMITTED", "FAILED"):
                return
                
            corrected_text = track_data["best_text"]
            weighted_conf = track_data["best_conf"]
            crop = track_data["best_crop"]
            frame = track_data.get("best_frame") # Need to store this
            
            if crop is None or frame is None:
                return
                
            category_name = "Unknown"
            category_code = "unknown"
            category_color = "gray"
            
            hotlist_entry = get_category(db, corrected_text)
            if hotlist_entry:
                category_name = hotlist_entry["category_name"]
                category_code = hotlist_entry["category_code"]
                category_color = hotlist_entry["category_color"]
                
            record = crud.create_record(db, {
                "plate": corrected_text,
                "raw_text": corrected_text,
                "confidence": int(weighted_conf * 100),
                "site": "Goa Airport",
                "camera": "CAM_ENTRY_PLATE",
                "category": category_name,
                "category_name": category_name,
                "category_code": category_code,
                "category_color": category_color,
                "plate_image_url": None,
                "driver_image_url": None,
                "model_used": load_selected_model(),
                "detector_used": "YOLOv8_Tracking_VideoUpload",
                "image_storage_type": "filesystem"
            })
                
            dt = record.time
            storage_dir = os.path.join(base_dir, "storage", f"{dt.year}", f"{dt.month:02d}", f"{dt.day:02d}")
            os.makedirs(storage_dir, exist_ok=True)
            
            plate_file = f"plate_{record.id}.jpg"
            plate_path = os.path.join(storage_dir, plate_file)
            cv2.imwrite(plate_path, crop)
            record.plate_image_url = f"storage/{dt.year}/{dt.month:02d}/{dt.day:02d}/{plate_file}"
            
            db.commit()
            db.refresh(record)
            
            _, crop_buffer = cv2.imencode('.jpg', crop)
            crop_str = base64.b64encode(crop_buffer).decode('utf-8')
            
            _, full_buffer = cv2.imencode('.jpg', frame)
            img_str = base64.b64encode(full_buffer).decode('utf-8')
            
            detected_records.append({
                "id": record.id,
                "plate": corrected_text,
                "confidence": weighted_conf,
                "category": category_name,
                "camera": "CAM_ENTRY_PLATE",
                "time": record.time.isoformat(),
                "plate_image_url": f"data:image/jpeg;base64,{crop_str}",
                "image": img_str
            })
            track_data["state"] = "COMMITTED"
            print(f"[ANPR Summary] Track {t_id} finalized | Plate: {corrected_text} | Conf: {weighted_conf:.2f} | OCR Samples: {len(track_data.get('ocr_history', []))}")
        
        # Read and process frames sequentially
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
                
            frame_count += 1
            if frame_count % frame_skip != 0:
                continue
                
            try:
                results = vehicle_tracker.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)
                boxes = results[0].boxes
            except Exception as e:
                print(f"[VideoUpload] Tracker exception on frame {frame_count}: {e}")
                boxes = []
                
            tracked_vehicles = []
            vehicle_classes = [2, 3, 5, 7]
            
            if boxes is not None:
                for box in boxes:
                    if box.id is not None and int(box.cls[0]) in vehicle_classes:
                        t_id = int(box.id[0])
                        # Ignore finalized/completed tracks to save CPU
                        if t_id in completed_tracks:
                            continue
                            
                        conf = float(box.conf[0])
                        if conf >= settings.get("vehicle_detector_conf", 0.40):
                            xyxy = box.xyxy[0].tolist()
                            vx1, vy1, vx2, vy2 = map(int, xyxy)
                            if (vx2 - vx1) >= 80 and (vy2 - vy1) >= 80:
                                tracked_vehicles.append((t_id, (vx1, vy1, vx2, vy2), conf))
                        
            now_monotonic = time.monotonic()
            
            for t_id, (vx1, vy1, vx2, vy2), v_conf in tracked_vehicles:
                if t_id not in local_cache:
                    local_cache[t_id] = {
                        "state": "DETECTED",
                        "best_crop": None,
                        "best_frame": None,
                        "best_text": None,
                        "best_conf": 0.0,
                        "ocr_history": [],
                        "start_ts": now_monotonic,
                        "last_seen": now_monotonic,
                        "frames_tracked": 0,
                        "roi_dwell_start": now_monotonic,
                        "candidates": [],
                        "best_pre_score": 0.0,
                        "vehicle_crops": [],
                        "ocr_crop_cache": []
                    }
                track = local_cache[t_id]
                track["last_seen"] = now_monotonic
                track["frames_tracked"] += 1
                
                dwell_time = now_monotonic - track["roi_dwell_start"]
                cy = (vy1 + vy2) / 2.0
                virtual_line_y = frame.shape[0] * 0.5
                crossed_line = abs(cy - virtual_line_y) <= 30.0
                
                is_triggered = (track["frames_tracked"] >= settings.get("min_track_age", 5)) and (
                    crossed_line or (dwell_time >= settings.get("roi_dwell_time", 0.3))
                )
                
                vh, vw = frame.shape[:2]
                vx1_c = max(0, vx1)
                vy1_c = max(0, vy1)
                vx2_c = min(vw, vx2)
                vy2_c = min(vh, vy2)
                vehicle_crop = frame[vy1_c:vy2_c, vx1_c:vx2_c]
                
                if track["state"] == "DETECTED":
                    # Buffer vehicle crops
                    track["vehicle_crops"].append({
                        "crop": vehicle_crop,
                        "frame": frame.copy(),
                        "box": (vx1, vy1, vx2, vy2)
                    })
                    if len(track["vehicle_crops"]) > 15:
                        track["vehicle_crops"].pop(0)
                        
                    if is_triggered:
                        track["state"] = "OCR_PENDING"
                        detected_plates = []
                        
                        # Rank vehicle crops using composite quality score
                        scored_crops = []
                        for item in track["vehicle_crops"]:
                            vc = item["crop"]
                            if vc is None or vc.size == 0:
                                continue
                            try:
                                gray_vc = cv2.cvtColor(vc, cv2.COLOR_BGR2GRAY)
                                lap_var = cv2.Laplacian(gray_vc, cv2.CV_64F).var()
                                item_vh, item_vw = vc.shape[:2]
                                area = item_vh * item_vw
                                brightness = np.mean(gray_vc)
                                
                                sharpness_score = min(1.0, lap_var / 500.0)
                                size_score = min(1.0, area / 200000.0)
                                brightness_score = 1.0 - abs(brightness - 127.5) / 127.5
                                
                                composite_score = 0.50 * sharpness_score + 0.30 * size_score + 0.20 * brightness_score
                                scored_crops.append((composite_score, item))
                            except Exception:
                                scored_crops.append((0.0, item))
                                
                        scored_crops.sort(key=lambda x: x[0], reverse=True)
                        crops_to_process = [x[1] for x in scored_crops[:5]]
                        
                        for item in crops_to_process:
                            try:
                                vc = item["crop"]
                                p_crop, p_box, p_conf = detect_plate_in_roi(vc, plate_model, settings)
                                if p_crop is None:
                                    vbox = item["box"]
                                    fframe = item["frame"]
                                    fvh, fvw = fframe.shape[:2]
                                    padding = max(20, int(0.10 * (vbox[2] - vbox[0])))
                                    pad_x1 = max(0, vbox[0] - padding)
                                    pad_y1 = max(0, vbox[1] - padding)
                                    pad_x2 = min(fvw, vbox[2] + padding)
                                    pad_y2 = min(fvh, vbox[3] + padding)
                                    padded_crop = fframe[pad_y1:pad_y2, pad_x1:pad_x2]
                                    p_crop, p_box, p_conf = detect_plate_in_roi(padded_crop, plate_model, settings)
                                    
                                if p_crop is not None:
                                    gray_crop = cv2.cvtColor(p_crop, cv2.COLOR_BGR2GRAY)
                                    lap_var = cv2.Laplacian(gray_crop, cv2.CV_64F).var()
                                    persp = calculate_perspective_score(p_crop)
                                    brightness = np.mean(gray_crop)
                                    ph, pw = p_crop.shape[:2]
                                    
                                    is_rejected = (lap_var < 20) or (pw < 40) or (ph < 12) or (brightness < 30) or (brightness > 230)
                                    if not is_rejected:
                                        pre_score = calculate_pre_ocr_score(p_conf, lap_var, persp, brightness, pw, ph)
                                        detected_plates.append((pre_score, p_crop, p_conf, item["frame"]))
                            except Exception as e:
                                print(f"Exception extracting plate: {e}")
                                
                        if not detected_plates:
                            print(f"[ANPR Telemetry] Video Upload Track {t_id} | Status: FAILED | Reason: PLATE_NOT_FOUND")
                            track["state"] = "FAILED"
                        else:
                            detected_plates.sort(key=lambda x: x[0], reverse=True)
                            top_candidates = detected_plates[:settings.get("ocr_candidates", 2)]
                            
                            from services.detection import reader, _sort_ocr_result
                            early_exit_triggered = False
                            
                            for score, crop, det_conf, fframe in top_candidates:
                                try:
                                    # Check cache for similar crops first
                                    cached_res = None
                                    for cached_crop, ocr_history_subset in track.setdefault("ocr_crop_cache", []):
                                        if are_crops_similar(crop, cached_crop, threshold=0.92):
                                            cached_res = ocr_history_subset
                                            total_cache_hits += 1
                                            break
                                    
                                    if cached_res is not None:
                                        # print(f"[OCR Cache] Reused {len(cached_res)} reads for Track {t_id}")
                                        track["ocr_history"].extend(cached_res)
                                        for norm_text, confidence in cached_res:
                                            corrected_info = post_process_indian_plate(norm_text)
                                            corrected_text = corrected_info["plate"]
                                            is_valid_format = CLASSIC_PLATE_RE.match(corrected_text) or BH_PLATE_RE.match(corrected_text)
                                            if confidence >= 0.90 and is_valid_format:
                                                early_exit_triggered = True
                                                break
                                        if early_exit_triggered:
                                            # Early exit logic: assign best immediately
                                            track["best_text"] = corrected_text
                                            track["best_conf"] = confidence
                                            track["best_crop"] = crop
                                            track["best_frame"] = fframe
                                            track["state"] = "VERIFIED"
                                            break
                                        continue
                                        
                                    crop_ocr_history = []
                                    variants = get_ocr_variants(crop)
                                    total_ocr_executions += len(variants)
                                    for variant in variants:
                                        result = reader.readtext(variant, detail=1, paragraph=False)
                                        if not result:
                                            continue
                                        sorted_res = _sort_ocr_result(result)
                                        raw_text = "".join(text for _, text, _ in sorted_res)
                                        confs = [float(prob) for _, _, prob in sorted_res]
                                        confidence = max(confs) if confs else 0.0
                                        if confidence >= settings.get("ocr_confidence_floor", 0.65):
                                            norm_text = normalize_plate_string(raw_text)
                                            if norm_text:
                                                crop_ocr_history.append((norm_text, confidence))
                                                
                                                # Early exit check
                                                corrected_info = post_process_indian_plate(norm_text)
                                                corrected_text = corrected_info["plate"]
                                                is_valid_format = CLASSIC_PLATE_RE.match(corrected_text) or BH_PLATE_RE.match(corrected_text)
                                                if confidence >= 0.90 and is_valid_format:
                                                    print(f"[OCR Early Exit] High confidence match: {corrected_text} ({confidence:.2f})")
                                                    early_exit_triggered = True
                                                    track["best_text"] = corrected_text
                                                    track["best_conf"] = confidence
                                                    track["best_crop"] = crop
                                                    track["best_frame"] = fframe
                                                    track["state"] = "VERIFIED"
                                                    break
                                    
                                    track["ocr_history"].extend(crop_ocr_history)
                                    track.setdefault("ocr_crop_cache", []).append((crop, crop_ocr_history))
                                    
                                    if early_exit_triggered:
                                        break
                                except Exception as e:
                                    print(f"Exception during OCR logic: {e}")
                                    
                            if not early_exit_triggered and track["ocr_history"]:
                                try:
                                    best_text, weighted_conf, agreement_rate, votes = weighted_voting(track["ocr_history"])
                                    if best_text:
                                        corrected_info = post_process_indian_plate(best_text)
                                        corrected_text = corrected_info["plate"]
                                        
                                        commit_threshold = settings.get("plate_commit_threshold", 0.90)
                                        is_stable = False
                                        if weighted_conf >= commit_threshold:
                                            is_stable = True
                                        elif votes >= 2 and agreement_rate >= 0.75:
                                            is_stable = True
                                            
                                        if is_stable:
                                            track["best_text"] = corrected_text
                                            track["best_conf"] = weighted_conf
                                            
                                            # Find best crop
                                            if top_candidates:
                                                track["best_crop"] = top_candidates[0][1]
                                                track["best_frame"] = top_candidates[0][3]
                                                
                                            track["state"] = "VERIFIED"
                                except Exception as e:
                                    print(f"Exception in voting: {e}")

                # Immediate commit & cleanup on early exit / VERIFIED state
                if track["state"] == "VERIFIED":
                    commit_track(t_id, track)
                    print(f"[Memory Management] Freeing local_cache for Track {t_id} (Early Exit / Stable)")
                    del local_cache[t_id]
                    completed_tracks.add(t_id)

            # Expiration Loop: Clean up stale tracks (e.g. left the frame)
            expired_t_ids = []
            for cache_t_id, cache_track in list(local_cache.items()):
                if now_monotonic - cache_track["last_seen"] > 2.0:
                    expired_t_ids.append(cache_t_id)
                    
            for exp_t_id in expired_t_ids:
                exp_track = local_cache[exp_t_id]
                
                # If they never reached VERIFIED, but we have some OCR history, we can force-evaluate
                if exp_track["state"] not in ("COMMITTED", "VERIFIED", "FAILED") and exp_track.get("ocr_history"):
                    try:
                        best_text, weighted_conf, agreement_rate, votes = weighted_voting(exp_track["ocr_history"])
                        if best_text:
                            corrected_info = post_process_indian_plate(best_text)
                            exp_track["best_text"] = corrected_info["plate"]
                            exp_track["best_conf"] = weighted_conf
                            
                            # Use last buffered crop if no top candidates explicitly saved
                            if exp_track.get("vehicle_crops") and exp_track.get("best_crop") is None:
                                exp_track["best_crop"] = exp_track["vehicle_crops"][-1]["crop"]
                                exp_track["best_frame"] = exp_track["vehicle_crops"][-1]["frame"]
                                
                            exp_track["state"] = "VERIFIED"
                    except Exception as e:
                        print(f"Exception on forced track expiration for {exp_t_id}: {e}")
                        
                if exp_track["state"] == "VERIFIED":
                    commit_track(exp_t_id, exp_track)
                
                # Free memory
                del local_cache[exp_t_id]
                completed_tracks.add(exp_t_id)
                print(f"[Memory Management] Freeing local_cache for Track {exp_t_id} (Expired)")

        cap.release()
        
        # Flush any remaining tracks at end of video
        for cache_t_id, cache_track in list(local_cache.items()):
            if cache_track["state"] not in ("COMMITTED", "VERIFIED", "FAILED") and cache_track.get("ocr_history"):
                best_text, weighted_conf, agreement_rate, votes = weighted_voting(cache_track["ocr_history"])
                if best_text:
                    corrected_info = post_process_indian_plate(best_text)
                    cache_track["best_text"] = corrected_info["plate"]
                    cache_track["best_conf"] = weighted_conf
                    if cache_track.get("vehicle_crops") and cache_track.get("best_crop") is None:
                        cache_track["best_crop"] = cache_track["vehicle_crops"][-1]["crop"]
                        cache_track["best_frame"] = cache_track["vehicle_crops"][-1]["frame"]
                    cache_track["state"] = "VERIFIED"
                    
            if cache_track["state"] == "VERIFIED":
                commit_track(cache_t_id, cache_track)
                
            print(f"[Memory Management] Freeing local_cache for Track {cache_t_id} (End of Video)")
            del local_cache[cache_t_id]

        total_time = time.time() - start_time_overall
        print("\n" + "="*50)
        print(f"[Video Processing Summary]")
        print(f"Frames Processed: {frame_count}")
        print(f"Total Unique Vehicles: {len(completed_tracks)}")
        print(f"OCR Executions: {total_ocr_executions}")
        print(f"OCR Cache Hits: {total_cache_hits}")
        print(f"Total Runtime: {total_time:.2f} seconds")
        print("="*50 + "\n")
        
        return {"detected": detected_records}
        
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
