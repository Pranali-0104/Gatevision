import threading
import time
from database import SessionLocal
import crud
from services.storage import save_event_images

# Configuration
MATCH_TIMEOUT_SEC = 2.0  # Configurable 2-second match window
MATCHER_POLL_INTERVAL = 0.5

# In-memory queues
driver_events = []
plate_events = []
matcher_lock = threading.Lock()

def push_driver_event(timestamp, camera_id, gate_id, lane, direction, driver_crop):
    """Called by the Driver Camera pipeline when a face is captured."""
    event = {
        "type": "DRIVER",
        "timestamp": timestamp,
        "camera_id": camera_id,
        "gate_id": gate_id,
        "lane": lane,
        "direction": direction,
        "driver_crop":driver_crop,
        "PRANALI GOING V",
    }
    with matcher_lock:
        driver_events.append(event)
    print(f"[MATCHER] Pushed Driver Event from {camera_id} at {timestamp:.2f}")

def push_plate_event(timestamp, camera_id, gate_id, lane, direction, plate_text, confidence, vehicle_crop, plate_crop):
    """Called by the Plate Camera pipeline when an OCR is completed."""
    event = {
        "type": "PLATE",
        "timestamp": timestamp,
        "camera_id": camera_id,
        "gate_id": gate_id,
        "lane": lane,
        "direction": direction,
        "plate_text": plate_text,
        "confidence": confidence,
        "vehicle_crop": vehicle_crop,
        "plate_crop": plate_crop,
    }
    with matcher_lock:
        plate_events.append(event)
    print(f"[MATCHER] Pushed Plate Event ({plate_text}) from {camera_id} at {timestamp:.2f}")

def _commit_vehicle_event(gate_id, lane, direction, plate_event, driver_event):
    """Takes matched (or solitary) events and commits them to the database."""
    print(f"[MATCHER] Committing VehicleEvent for Plate: {plate_event['plate_text'] if plate_event else 'Unknown'}")
    
    db = SessionLocal()
    try:
        # 1. Create a DB record placeholder to get the ID
        event_data = {
            "gate_id": gate_id,
            "lane": lane,
            "direction": direction,
            "plate_text": plate_event["plate_text"] if plate_event else "UNKNOWN",
            "confidence": plate_event["confidence"] if plate_event else 0,
            "camera_plate": plate_event["camera_id"] if plate_event else None,
            "camera_driver": driver_event["camera_id"] if driver_event else None,
        }
        
        db_event = crud.create_vehicle_event(db, event_data)
        
        # 2. Save Images         
        p_crop = plate_event["plate_crop"] if plate_event else None
        v_crop = plate_event["vehicle_crop"] if plate_event else None
        d_crop = driver_event["driver_crop"] if driver_event else None
        
        image_urls = save_event_images(db_event.id, p_crop, v_crop, d_crop)
        
        # 3. Update DB record with Image URLs
        if image_urls:
            for k, v in image_urls.items():
                setattr(db_event, k, v)
            db.commit()
            
    except Exception as e:
        print(f"[MATCHER Error] Failed to commit VehicleEvent: {e}")
    finally:
        db.close()

def _matcher_loop():

    
    """Background thread that constantly polls the queues for matches or timeouts."""
    global plate_events, driver_events
    
    while True:
        time.sleep(MATCHER_POLL_INTERVAL)
        now = time.monotonic()
        
        with matcher_lock:
            matched_plate_indices = set()
            matched_driver_indices = set()
            
            # 1. Try to match Plates with Drivers
            for p_idx, p_ev in enumerate(plate_events):
                best_match_idx = -1
                best_time_diff = MATCH_TIMEOUT_SEC + 1
                
                for d_idx, d_ev in enumerate(driver_events):
                    if d_idx in matched_driver_indices:
                        continue
                    
                    # Must be same gate and lane
                    if p_ev["gate_id"] != d_ev["gate_id"] or p_ev["lane"] != d_ev["lane"]:
                        continue
                        
                    time_diff = abs(p_ev["timestamp"] - d_ev["timestamp"])
                    if time_diff <= MATCH_TIMEOUT_SEC and time_diff < best_time_diff:
                        best_match_idx = d_idx
                        best_time_diff = time_diff
                        
                if best_match_idx != -1:
                    d_ev = driver_events[best_match_idx]
                    matched_plate_indices.add(p_idx)
                    matched_driver_indices.add(best_match_idx)
                    
                    _commit_vehicle_event(
                        p_ev["gate_id"], p_ev["lane"], p_ev["direction"],
                        p_ev, d_ev
                    )
            
            # 2. Process Timeouts for unmatched events
            for p_idx, p_ev in enumerate(plate_events):
                if p_idx not in matched_plate_indices:
                    if (now - p_ev["timestamp"]) > MATCH_TIMEOUT_SEC:
                        # Timeout! Commit plate without driver
                        matched_plate_indices.add(p_idx)
                        _commit_vehicle_event(
                            p_ev["gate_id"], p_ev["lane"], p_ev["direction"],
                            p_ev, None
                        )
                        
            for d_idx, d_ev in enumerate(driver_events):
                if d_idx not in matched_driver_indices:
                    if (now - d_ev["timestamp"]) > MATCH_TIMEOUT_SEC:
                        # Timeout! Driver without plate
                        # Depending on business logic, we could commit or drop. Let's commit as UNKNOWN plate.
                        matched_driver_indices.add(d_idx)
                        _commit_vehicle_event(
                            d_ev["gate_id"], d_ev["lane"], d_ev["direction"],
                            None, d_ev
                        )
                        
            # 3. Clean up matched/timeout events from queues
            plate_events = [ev for i, ev in enumerate(plate_events) if i not in matched_plate_indices]
            driver_events = [ev for i, ev in enumerate(driver_events) if i not in matched_driver_indices]

# Start the matcher thread automatically
matcher_thread = threading.Thread(target=_matcher_loop, daemon=True)
matcher_thread.start()
print("[MATCHER] Engine started.")
