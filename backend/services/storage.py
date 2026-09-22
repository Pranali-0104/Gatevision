import os
import cv2
from datetime import datetime

def save_event_images(vehicle_event_id, plate_crop=None, vehicle_crop=None, driver_crop=None):
    """
    Saves images associated with a vehicle event and returns a dict of URLs.
    """
    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "storage", "images")
    os.makedirs(save_dir, exist_ok=True)
    
    urls = {}
    
    if vehicle_crop is not None and vehicle_crop.size > 0:
        v_path = os.path.join(save_dir, f"{vehicle_event_id}_vehicle.jpg")
        cv2.imwrite(v_path, vehicle_crop)
        urls["vehicle_image_url"] = f"/storage/images/{vehicle_event_id}_vehicle.jpg"
        
    if plate_crop is not None and plate_crop.size > 0:
        p_path = os.path.join(save_dir, f"{vehicle_event_id}_plate.jpg")
        cv2.imwrite(p_path, plate_crop)
        urls["plate_image_url"] = f"/storage/images/{vehicle_event_id}_plate.jpg"
        
    if driver_crop is not None and driver_crop.size > 0:
        d_path = os.path.join(save_dir, f"{vehicle_event_id}_driver.jpg")
        cv2.imwrite(d_path, driver_crop)
        urls["driver_image_url"] = f"/storage/images/{vehicle_event_id}_driver.jpg"
        
    return urls
