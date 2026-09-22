import re
import os
import time
import threading
from pathlib import Path
import json

import cv2
import easyocr
import numpy as np
import torch
from ultralytics import YOLO

PLATE_CHAR_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_ocr_reader = None
_ocr_reader_lock = threading.Lock()

yolo_models = {}


def get_ocr_reader():
    global _ocr_reader
    with _ocr_reader_lock:
        if _ocr_reader is None:
            use_gpu = torch.cuda.is_available()
            print(f"[ANPR] Initializing EasyOCR (gpu={use_gpu})")
            _ocr_reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
        return _ocr_reader


class _LazyOCRReader:
    def readtext(self, *args, **kwargs):
        return get_ocr_reader().readtext(*args, **kwargs)


reader = _LazyOCRReader()

def load_selected_model():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings_file = os.path.join(base_dir, "settings.json")
    default_model = "YOLOv8n"
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                data = json.load(f)
                return data.get("selected_model", default_model)
        except Exception:
            pass
    return default_model

def get_detector(model_name):
    global yolo_models
    if model_name in yolo_models:
        return yolo_models[model_name]
        
    model_configs = {
        "YOLOv8n": "yolov8n_plate.pt",
        "YOLOv8s": "yolov8s_plate.pt",
        "YOLOv8m": "yolov8m_plate.pt"
    }
    
    if model_name not in model_configs:
        raise ValueError(f"[ANPR Warning] Unsupported model: {model_name}")
        
    weights_file = model_configs[model_name]
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    weights_path = os.path.join(base_dir, weights_file)
    
    if not os.path.exists(weights_path):
        error_msg = f"CRITICAL: Model weights file not found at {weights_path}. Runtime downloads are disabled."
        print(error_msg)
        raise FileNotFoundError(error_msg)
        
    try:
        yolo_models[model_name] = YOLO(weights_path)
        return yolo_models[model_name]
    except Exception as e:
        print(f"[ANPR Warning] Failed to load {model_name} model: {e}")
        raise RuntimeError(f"Failed to load {model_name} model: {e}") from e

def get_yolo_model():
    return get_detector("YOLOv8n")


def standardize_crop(crop_image):
    if crop_image is None:
        return None
    h, w = crop_image.shape[:2]
    max_w, max_h = 300, 100
    aspect = w / h
    
    new_w = max_w
    new_h = int(new_w / aspect)
    if new_h > max_h:
        new_h = max_h
        new_w = int(new_h * aspect)
        
    if w > max_w or h > max_h:
        return cv2.resize(crop_image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return crop_image


LETTER_FIXES = str.maketrans({
    "0": "O",
    "1": "I",
    "2": "Z",
    "4": "A",
    "5": "S",
    "6": "G",
    "8": "B",
})

DIGIT_FIXES = str.maketrans({
    "B": "8",
    "D": "0",
    "G": "6",
    "I": "1",
    "L": "4",
    "O": "0",
    "Q": "0",
    "S": "5",
    "T": "1",
    "Z": "2",
})

CLASSIC_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$")
BH_PLATE_RE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")


def _as_letters(text):
    return text.translate(LETTER_FIXES)


def _as_digits(text):
    return text.translate(DIGIT_FIXES)


def clean_plate(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _box_center(box):
    xs = [point[0] for point in box]
    ys = [point[1] for point in box]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _sort_ocr_result(result):
    if not result:
        return []

    heights = []
    for box, _, _ in result:
        ys = [point[1] for point in box]
        heights.append(max(ys) - min(ys))

    line_height = max(12, int(np.median(heights)))

    return sorted(
        result,
        key=lambda item: (
            round(_box_center(item[0])[1] / line_height),
            _box_center(item[0])[0],
        ),
    )


def _normalize_classic_plate(candidate):
    normalized = []
    for series_len in range(1, 4):
        expected_len = 2 + 2 + series_len + 4
        if len(candidate) != expected_len:
            continue

        state = _as_letters(candidate[:2])
        district = _as_digits(candidate[2:4])
        series = _as_letters(candidate[4:4 + series_len])
        number = _as_digits(candidate[4 + series_len:])
        plate = f"{state}{district}{series}{number}"

        if CLASSIC_PLATE_RE.match(plate):
            normalized.append(plate)

    return normalized


def _normalize_bh_plate(candidate):
    if len(candidate) not in (9, 10):
        return None

    year = _as_digits(candidate[:2])
    bh = _as_letters(candidate[2:4])
    number = _as_digits(candidate[4:8])
    suffix = _as_letters(candidate[8:])
    plate = f"{year}{bh}{number}{suffix}"

    if BH_PLATE_RE.match(plate):
        return plate

    return None


def _plate_candidates(text):
    compact = clean_plate(text)
    compact = compact.replace("IND", "")

    candidates = set()

    for size in range(9, 12):
        for start in range(0, max(1, len(compact) - size + 1)):
            window = compact[start:start + size]
            candidates.update(_normalize_classic_plate(window))

    for size in range(9, 11):
        for start in range(0, max(1, len(compact) - size + 1)):
            bh_candidate = _normalize_bh_plate(compact[start:start + size])
            if bh_candidate:
                candidates.add(bh_candidate)

    if CLASSIC_PLATE_RE.match(compact) or BH_PLATE_RE.match(compact):
        candidates.add(compact)

    if candidates:
        return list(candidates)

    return [compact] if 6 <= len(compact) <= 12 else []



DEFAULT_SETTINGS = {
    "vehicle_detector_conf": 0.40,
    "plate_detector_conf": 0.20,
    "retry_detector_conf": 0.10,
    "ocr_confidence_floor": 0.30,
    "min_track_age": 3,
    "roi_dwell_time": 0.0,
    "track_timeout": 2.0,
    "duplicate_suppression_s": 10.0,
    "max_candidates_per_track": 5,
    "ocr_candidates": 1,
    "plate_commit_threshold": 0.50,
    "lane_id": "LANE_1",
    "frame_skip": 5,
    "live_plate_scan_crops": 3,
    "live_ocr_max_variants": 2,
    "ocr_early_exit_conf": 0.88,
    "live_preview_jpeg_quality": 70,
    "live_preview_max_width": 960,
    "live_detection_fps": 3,
    "live_preview_fps": 5,
}

def are_crops_similar(crop1, crop2, threshold=0.92):
    if crop1 is None or crop2 is None:
        return False
    try:
        # Resize both to 32x32 grayscale
        c1 = cv2.resize(crop1, (32, 32))
        c2 = cv2.resize(crop2, (32, 32))
        c1_gray = cv2.cvtColor(c1, cv2.COLOR_BGR2GRAY) if len(c1.shape) == 3 else c1
        c2_gray = cv2.cvtColor(c2, cv2.COLOR_BGR2GRAY) if len(c2.shape) == 3 else c2
        res = cv2.matchTemplate(c1_gray, c2_gray, cv2.TM_CCOEFF_NORMED)
        return float(res[0][0]) >= threshold
    except Exception:
        return False


def load_settings():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings_file = os.path.join(base_dir, "settings.json")
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                data = json.load(f)
                for k, v in data.items():
                    if k in settings:
                        settings[k] = v
        except Exception:
            pass
    return settings

def calculate_perspective_score(crop_image):
    if crop_image is None or crop_image.size == 0:
        return 0.5
    try:
        gray = cv2.cvtColor(crop_image, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            rect = cv2.minAreaRect(largest)
            angle = rect[2]
            if angle < -45:
                angle = 90 + angle
            perspective_score = 1.0 - min(1.0, abs(angle) / 45.0)
            return float(perspective_score)
    except Exception:
        pass
    return 0.5

def calculate_pre_ocr_score(detector_conf, laplacian_var, perspective_score, brightness, w, h):
    sharpness_score = min(1.0, laplacian_var / 500.0)
    size_score = min(1.0, (w * h) / 30000.0)
    brightness_score = 1.0 - abs(brightness - 127.5) / 127.5
    
    pre_score = (
        0.40 * size_score +
        0.30 * sharpness_score +
        0.20 * detector_conf +
        0.10 * brightness_score
    )
    return float(pre_score)

def calculate_post_ocr_score(ocr_conf, detector_conf, agreement, pre_score):
    final_score = (
        0.40 * ocr_conf +
        0.25 * detector_conf +
        0.20 * agreement +
        0.15 * pre_score
    )
    return float(final_score)

def get_ocr_variants(crop_image, max_variants=3):
    variants = []
    if crop_image is None or crop_image.size == 0:
        return variants

    try:
        h, w = crop_image.shape[:2]
        # EasyOCR works best when text height is around 30-60 pixels.
        # Prevent unnecessary 2.5x upscaling that causes 10-second OCR lag.
        if h < 40 or w < 100:
            scale = min(2.5, 60.0 / max(1, h))
            new_w, new_h = int(w * scale), int(h * scale)
            crop_image = cv2.resize(crop_image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        elif h > 200 or w > 600:
            scale = max(0.4, 120.0 / h)
            new_w, new_h = int(w * scale), int(h * scale)
            crop_image = cv2.resize(crop_image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    except Exception as e:
        print(f"[ANPR Warning] Error preprocessing crop: {e}")

    variants.append(crop_image)
    if max_variants < 2:
        return variants

    try:
        gray = cv2.cvtColor(crop_image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        variants.append(enhanced)

        if max_variants < 3:
            return variants

        threshold = cv2.adaptiveThreshold(
            enhanced,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            7,
        )
        variants.append(threshold)
    except Exception as e:
        print(f"[ANPR Warning] Error generating OCR variants: {e}")

    return variants


def read_plate_ocr(crop_image, settings=None):
    """Progressive OCR for live stream — stops early on a confident valid plate."""
    if settings is None:
        settings = load_settings()

    max_variants = settings.get("live_ocr_max_variants", 2)
    ocr_floor = settings.get("ocr_confidence_floor", 0.65)
    early_conf = settings.get("ocr_early_exit_conf", 0.88)

    variants = get_ocr_variants(crop_image, max_variants=max_variants)
    if not variants:
        return [], False, None

    ocr_reader = get_ocr_reader()
    local_history = []
    early_exit_data = None

    for variant in variants:
        try:
            result = ocr_reader.readtext(
                variant,
                detail=1,
                paragraph=False,
                allowlist=PLATE_CHAR_ALLOWLIST,
            )
        except Exception as ocr_err:
            print(f"[ANPR Warning] OCR read error: {ocr_err}")
            continue

        if not result:
            continue

        sorted_res = _sort_ocr_result(result)
        raw_text = "".join(text for _, text, _ in sorted_res)
        confs = [float(prob) for _, _, prob in sorted_res]
        confidence = max(confs) if confs else 0.0

        if confidence < ocr_floor:
            continue

        norm_text = normalize_plate_string(raw_text)
        if not norm_text:
            continue

        local_history.append((norm_text, confidence))
        corrected_info = post_process_indian_plate(norm_text)
        corrected_text = corrected_info["plate"]
        
        # Track the best variant found so far
        if early_exit_data is None or confidence > early_exit_data["conf"]:
            early_exit_data = {"text": corrected_text, "conf": confidence}
            
        is_valid = CLASSIC_PLATE_RE.match(corrected_text) or BH_PLATE_RE.match(corrected_text)
        if confidence >= early_conf and is_valid:
            break

    return local_history, True if early_exit_data else False, early_exit_data

def normalize_plate_string(text):
    if not text:
        return ""
    cleaned = text.upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
    if cleaned.startswith("IND") and len(cleaned) > 7:
        cleaned = cleaned[3:]
    elif cleaned.endswith("IND") and len(cleaned) > 7:
        cleaned = cleaned[:-3]
    return cleaned

def weighted_voting(ocr_history):
    if not ocr_history:
        return "", 0.0, 0.0, 0
        
    votes = {}
    total_runs = len(ocr_history)
    
    for text, conf in ocr_history:
        if not text:
            continue
        if text not in votes:
            votes[text] = {"weight": 0.0, "count": 0, "max_conf": 0.0}
        votes[text]["weight"] += conf
        votes[text]["count"] += 1
        if conf > votes[text]["max_conf"]:
            votes[text]["max_conf"] = conf
            
    if not votes:
        return "", 0.0, 0.0, 0
        
    best_text = max(votes.keys(), key=lambda t: votes[t]["weight"])
    winner = votes[best_text]
    
    weighted_conf = winner["weight"] / winner["count"]
    agreement_rate = winner["count"] / total_runs
    
    return best_text, weighted_conf, agreement_rate, winner["count"]

def detect_plate_in_roi(vehicle_crop, plate_model, settings=None):
    if vehicle_crop is None or vehicle_crop.size == 0:
        return None, None, 0.0
        
    if settings is None:
        settings = load_settings()
        
    primary_conf = settings.get("plate_detector_conf", 0.30)
    retry_conf = settings.get("retry_detector_conf", 0.15)
    
    try:
        results = plate_model(vehicle_crop, conf=primary_conf, verbose=False)
        boxes = results[0].boxes
        if len(boxes) > 0:
            best_idx = int(np.argmax([float(b.conf[0]) for b in boxes]))
            xyxy = boxes[best_idx].xyxy[0].tolist()
            x1, y1, x2, y2 = map(int, xyxy)
            detector_conf = float(boxes[best_idx].conf[0])
            plate_crop = _crop_with_padding(vehicle_crop, (x1, y1, x2 - x1, y2 - y1))
            return plate_crop, (x1, y1, x2, y2), detector_conf
    except Exception as e:
        print(f"[ANPR Warning] Plate detector primary run error: {e}")
        
    try:
        results = plate_model(vehicle_crop, conf=retry_conf, verbose=False)
        boxes = results[0].boxes
        if len(boxes) > 0:
            best_idx = int(np.argmax([float(b.conf[0]) for b in boxes]))
            xyxy = boxes[best_idx].xyxy[0].tolist()
            x1, y1, x2, y2 = map(int, xyxy)
            detector_conf = float(boxes[best_idx].conf[0])
            plate_crop = _crop_with_padding(vehicle_crop, (x1, y1, x2 - x1, y2 - y1))
            return plate_crop, (x1, y1, x2, y2), detector_conf
    except Exception:
        pass
        
    return None, None, 0.0


def detect_plates_in_rois(vehicle_crops, plate_model, settings=None):
    """Batch plate detection — one YOLO forward pass for multiple vehicle crops."""
    if settings is None:
        settings = load_settings()

    primary_conf = settings.get("plate_detector_conf", 0.30)
    retry_conf = settings.get("retry_detector_conf", 0.15)

    indexed_crops = []
    for idx, crop in enumerate(vehicle_crops):
        if crop is not None and crop.size > 0:
            indexed_crops.append((idx, crop))

    if not indexed_crops:
        return {}

    indices, crops = zip(*indexed_crops)
    detections = {}

    def _best_from_results(batch_results, source_crops, crop_indices):
        found = {}
        for crop_idx, result, source_crop in zip(crop_indices, batch_results, source_crops):
            boxes = result.boxes
            if len(boxes) == 0:
                continue
            best_idx = int(np.argmax([float(b.conf[0]) for b in boxes]))
            xyxy = boxes[best_idx].xyxy[0].tolist()
            x1, y1, x2, y2 = map(int, xyxy)
            detector_conf = float(boxes[best_idx].conf[0])
            plate_crop = _crop_with_padding(source_crop, (x1, y1, x2 - x1, y2 - y1))
            found[crop_idx] = (plate_crop, (x1, y1, x2, y2), detector_conf)
        return found

    try:
        batch_results = plate_model(list(crops), conf=primary_conf, verbose=False)
        detections.update(_best_from_results(batch_results, crops, indices))
    except Exception as e:
        print(f"[ANPR Warning] Batch plate detector primary run error: {e}")

    missing = [idx for idx in indices if idx not in detections]
    if missing:
        retry_crops = [vehicle_crops[idx] for idx in missing]
        try:
            batch_results = plate_model(retry_crops, conf=retry_conf, verbose=False)
            detections.update(_best_from_results(batch_results, retry_crops, missing))
        except Exception:
            pass

    return detections


def _candidate_score(candidate, confidence, source_rank):
    score = confidence * 10 - source_rank

    if CLASSIC_PLATE_RE.match(candidate) or BH_PLATE_RE.match(candidate):
        score += 25

    if 9 <= len(candidate) <= 11:
        score += 3

    return score


def _image_variants(image):
    variants = [image]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    variants.append(gray)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    variants.append(enhanced)

    threshold = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )
    variants.append(threshold)

    return variants



def _detect_plate_regions(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)

    candidates = []

    edged = cv2.Canny(gray, 60, 180)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
    closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    image_area = image.shape[0] * image.shape[1]
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:25]:
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = w / float(h)
        area_ratio = (w * h) / float(image_area)

        if 2.0 <= aspect_ratio <= 6.8 and w >= 20 and h >= 6 and 0.001 <= area_ratio <= 0.18:
            candidates.append((x, y, w, h))

    if not candidates:
        contours, _ = cv2.findContours(edged, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:15]:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)
            if 2.0 <= aspect_ratio <= 6.8 and w >= 20 and h >= 6:
                candidates.append((x, y, w, h))

    unique = []
    seen = set()
    for x, y, w, h in candidates:
        key = (round(x / 10), round(y / 10), round(w / 10), round(h / 10))
        if key not in seen:
            seen.add(key)
            unique.append((x, y, w, h))

    return unique[:8]


def _crop_with_padding(image, box, pad_ratio=0.25):
    x, y, w, h = box
    pad_x = int(w * pad_ratio)
    pad_y = int(h * pad_ratio)
    y1 = max(0, y - pad_y)
    y2 = min(image.shape[0], y + h + pad_y)
    x1 = max(0, x - pad_x)
    x2 = min(image.shape[1], x + w + pad_x)
    return image[y1:y2, x1:x2]


def post_process_indian_plate(raw_ocr: str) -> dict:
    cleaned_raw = re.sub(r"[^A-Z0-9]", "", raw_ocr.upper())
    cleaned_raw = cleaned_raw.replace("IND", "")
    
    letter_to_digit = {
        'O': '0', 'I': '1', 'L': '1', 'S': '5', 'B': '8', 'Z': '2', 'G': '6', 'D': '0', 'A': '4', 'T': '7', 'Q': '0', 'E': '3', 'J': '3'
    }
    digit_to_letter = {
        '0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B', '6': 'G', '4': 'A', '7': 'T', '3': 'E'
    }
    
    def to_digit(c):
        return letter_to_digit.get(c, c)
    def to_letter(c):
        return digit_to_letter.get(c, c)
        
    classic_re = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$")
    bh_re = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")
    
    if classic_re.match(cleaned_raw) or bh_re.match(cleaned_raw):
        return {
            "raw_text": cleaned_raw,
            "plate": cleaned_raw,
            "corrected": False,
            "is_valid": True
        }
        
    n = len(cleaned_raw)
    patterns = []
    
    if n == 9:
        patterns.append(("classic", ["L", "L", "D", "D", "L", "D", "D", "D", "D"]))
        patterns.append(("bh", ["D", "D", "L", "L", "D", "D", "D", "D", "L"]))
    elif n == 10:
        patterns.append(("classic", ["L", "L", "D", "D", "L", "L", "D", "D", "D", "D"]))
        patterns.append(("bh", ["D", "D", "L", "L", "D", "D", "D", "D", "L", "L"]))
    elif n == 11:
        patterns.append(("classic", ["L", "L", "D", "D", "L", "L", "L", "D", "D", "D", "D"]))
        
    for ptype, pchars in patterns:
        candidate_chars = []
        for i, char in enumerate(cleaned_raw):
            expected = pchars[i]
            if expected == "L":
                candidate_chars.append(to_letter(char))
            else:
                candidate_chars.append(to_digit(char))
        candidate = "".join(candidate_chars)
        
        if ptype == "classic" and classic_re.match(candidate):
            return {
                "raw_text": cleaned_raw,
                "plate": candidate,
                "corrected": True,
                "is_valid": True
            }
        elif ptype == "bh" and bh_re.match(candidate):
            if candidate[2:4] == "BH":
                return {
                    "raw_text": cleaned_raw,
                    "plate": candidate,
                    "corrected": True,
                    "is_valid": True
                }
                
    return {
        "raw_text": cleaned_raw,
        "plate": cleaned_raw,
        "corrected": False,
        "is_valid": False
    }


def _read_plate_from_image(image, source_rank):
    scored_candidates = []
    variants = _image_variants(image)

    for idx, variant in enumerate(variants):
        start_var = time.perf_counter()
        result = reader.readtext(variant, detail=1, paragraph=False)
        var_time = (time.perf_counter() - start_var) * 1000
        print(f"  [ANPR Timing] OCR Variant {idx + 1}/{len(variants)} took {var_time:.2f} ms")

        result = _sort_ocr_result(result)

        raw_text = "".join(text for _, text, _ in result)
        confidence = max([float(prob) for _, _, prob in result], default=0.0)

        processed = post_process_indian_plate(raw_text)
        candidate = processed["plate"]
        scored_candidates.append((
            _candidate_score(candidate, confidence, source_rank),
            candidate,
            confidence,
            processed["raw_text"],
            processed["corrected"]
        ))

        for _, text, prob in result:
            processed = post_process_indian_plate(text)
            candidate = processed["plate"]
            scored_candidates.append((
                _candidate_score(candidate, float(prob), source_rank + 1),
                candidate,
                float(prob),
                processed["raw_text"],
                processed["corrected"]
            ))

    if not scored_candidates:
        return None

    scored_candidates.sort(reverse=True)
    return scored_candidates[0]


def detect_plate(image):
    selected_model = load_selected_model()
    
    if image is None:
        return "Not Found", image, "", "None", "Not Found", False, 0.0

    start_total = time.perf_counter()

    best = None
    best_box = None
    detector_used = selected_model
    best_idx = -1
    boxes = []

    # 1. Run YOLO detector
    try:
        yolo = get_detector(selected_model)
        if yolo is None:
            raise Exception(f"Model {selected_model} weights missing or failed to load")
            
        print("[YOLO] Model loaded")
        print("[YOLO] Inference started")
        results = yolo(image, verbose=False)
        boxes = results[0].boxes
        
        if len(boxes) > 0:
            best_conf = -1
            for i, box in enumerate(boxes):
                conf = float(box.conf[0])
                if conf > best_conf:
                    best_conf = conf
                    best_idx = i
            
            if best_idx != -1:
                xyxy = boxes[best_idx].xyxy[0].tolist()
                x1, y1, x2, y2 = map(int, xyxy)
                w = x2 - x1
                h = y2 - y1
                best_box = (x1, y1, w, h)
                print(f"[YOLO] Bounding box found: {best_box}")
                print(f"[YOLO] Confidence: {best_conf}")
                
                crop = _crop_with_padding(image, best_box)
                print("[YOLO] Crop generated")
                
                print("[OCR] Recognition started")
                result = _read_plate_from_image(crop, 0)
                if result:
                    best = result
    except Exception as e:
        print(f"[ANPR Warning] YOLO detector ({selected_model}) error: {e}")

    # 2. OpenCV contour fallback if YOLO failed or found nothing
    if best is None:
        detector_used = "OpenCV_Fallback"
        start_regions = time.perf_counter()
        regions = _detect_plate_regions(image)
        regions_time = (time.perf_counter() - start_regions) * 1000
        print(f"[ANPR Timing] Plate region proposal took {regions_time:.2f} ms")

        for rank, box in enumerate(regions):
            start_crop = time.perf_counter()
            crop = _crop_with_padding(image, box)
            crop_time = (time.perf_counter() - start_crop) * 1000
            print(f"[ANPR Timing] Region {rank + 1} cropping took {crop_time:.2f} ms")

            start_ocr = time.perf_counter()
            print("[OCR] Recognition started")
            result = _read_plate_from_image(crop, rank)
            ocr_time = (time.perf_counter() - start_ocr) * 1000
            print(f"[ANPR Timing] Region {rank + 1} OCR took {ocr_time:.2f} ms")

            if result and (best is None or result[0] > best[0]):
                best = result
                best_box = box

        # Fallback OCR logic on full image
        start_ocr_full = time.perf_counter()
        print("[OCR] Recognition started")
        full_image_result = _read_plate_from_image(image, 10)
        ocr_full_time = (time.perf_counter() - start_ocr_full) * 1000
        print(f"[ANPR Timing] Full Image Fallback OCR took {ocr_full_time:.2f} ms")

        if full_image_result and (best is None or full_image_result[0] > best[0]):
            best = full_image_result
            best_box = None

    plate_text = best[1] if best else "Not Found"
    raw_text = best[3] if best else "Not Found"
    corrected = best[4] if best else False

    if best is None:
        detector_used = "None"
        
    processed_image = image.copy()

    if best_box is not None:
        final_crop = _crop_with_padding(image, best_box)
        final_crop = standardize_crop(final_crop)
    else:
        final_crop = None

    # Save debug crops/detections
    crop_path_str = ""
    if best and final_crop is not None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        debug_dir = Path(os.path.join(base_dir, "debug_crops"))
        debug_dir.mkdir(exist_ok=True, parents=True)
        crop_filename = f"crop_{int(time.time() * 1000)}.jpg"
        crop_path = debug_dir / crop_filename

        cv2.imwrite(str(crop_path), final_crop)
        crop_path_str = str(crop_path).replace("\\", "/")

        abs_crop_path = os.path.abspath(crop_path)
        print(f"[ANPR Debug] Crop image saved to: {crop_path_str}")

    yolo_conf = 0.0
    if detector_used.startswith("YOLOv8") and best_idx != -1:
        try:
            yolo_conf = float(boxes[best_idx].conf[0])
        except Exception:
            pass
    ocr_conf = float(best[2]) if best else 0.0
    conf_value = yolo_conf if detector_used.startswith("YOLOv8") else ocr_conf

    # Draw box on processed image ONLY for YOLO detection
    if best_box and detector_used.startswith("YOLOv8"):
        x, y, w, h = best_box
        cv2.rectangle(processed_image, (x, y), (x + w, y + h), (0, 255, 0), 2)

    # Save to debug_detections/
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        debug_det_dir = Path(os.path.join(base_dir, "debug_detections"))
        debug_det_dir.mkdir(exist_ok=True, parents=True)
        cv2.imwrite(str(debug_det_dir / "original.jpg"), image)
        
        if final_crop is not None:
            cv2.imwrite(str(debug_det_dir / "crop.jpg"), final_crop)
        
        cv2.imwrite(str(debug_det_dir / "annotated.jpg"), processed_image)
        
        metadata = {
            "detector_used": detector_used,
            "model_used": selected_model,
            "confidence": conf_value,
            "bounding_box": list(best_box) if best_box is not None else None,
            "plate": plate_text,
            "timestamp": time.time()
        }
        with open(debug_det_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=4)
    except Exception as ex:
        print(f"[ANPR] Error saving debug_detections: {ex}")

    total_time = (time.perf_counter() - start_total) * 1000
    print(f"[ANPR Timing] Total detect_plate took {total_time:.2f} ms")

    return plate_text, processed_image, crop_path_str, detector_used, raw_text, corrected, conf_value, final_crop
