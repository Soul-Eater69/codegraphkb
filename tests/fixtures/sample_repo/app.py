"""Toy FastAPI app used to exercise CodeGraphKB end-to-end in tests."""
from .services import IdeaCardIngestionService


class FakeApp:
    def __init__(self):
        self.routes = {}

    def post(self, path):
        def decorator(fn):
            self.routes[("POST", path)] = fn
            return fn
        return decorator


app = FakeApp()
service = IdeaCardIngestionService()


@app.post("/idea-cards/upload")
def upload_idea_card(payload):
    """Validate payload then hand off to the ingestion service."""
    return service.process_upload(payload)
