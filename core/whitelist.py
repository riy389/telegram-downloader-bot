from utils.config import ALLOWED_USER_ID


def is_allowed(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID
