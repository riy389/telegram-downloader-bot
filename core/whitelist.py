from utils.config import ALLOWED_USER_ID, ALLOWED_USER_IDS


def is_allowed(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID or user_id in ALLOWED_USER_IDS
