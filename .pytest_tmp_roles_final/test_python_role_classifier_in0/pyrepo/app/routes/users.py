from app.services.user_service import create_user

def create_user_route(payload):
    return create_user(payload)
