import crud

def get_category(db, plate_text):
    entry = crud.get_hotlist_by_plate(db, plate_text)
    if entry:
        return entry
    return None
