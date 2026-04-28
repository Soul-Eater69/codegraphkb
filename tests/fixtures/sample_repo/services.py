"""Service layer for the toy app."""


def validate_file_type(payload):
    return True


def extract_text(payload):
    return ""


class IdeaCardIngestionService:
    """Validates uploads, extracts text, and writes records."""

    def process_upload(self, payload):
        if not validate_file_type(payload):
            raise ValueError("bad type")
        text = extract_text(payload)
        return self.save(payload, text)

    def save(self, payload, text):
        return {"id": "card_1", "text": text}
