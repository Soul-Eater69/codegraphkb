from app.repositories.user_repository import save_user

def create_user(payload):
    return save_user(payload)
