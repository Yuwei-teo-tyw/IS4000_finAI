"""Ingest an uploaded meeting-note file into the meeting-notes store.

PDF (text layer) and TXT only. Scanned PDFs, DOCX and audio are rejected with a clear
reason rather than stored empty. Extracted text is stored as untrusted data.
"""
import io
import re
import time
from datetime import date

from .schemas import ToolResult
from .store import UPLOAD_ID_PREFIX, DocumentStore, MeetingNoteDoc

MAX_BYTES = 10 * 1024 * 1024
_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG_DATE = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}


class IngestError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if len(data) > MAX_BYTES:
        raise IngestError("File is larger than 10 MB.", 413)
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        try:
            text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        except Exception as e:  # corrupt/encrypted
            raise IngestError(f"Could not read the PDF ({type(e).__name__}).") from e
    elif name.endswith(".txt"):
        text = data.decode("utf-8", errors="replace")
    else:
        raise IngestError("Only .pdf and .txt can be ingested into the meeting notes database for now.", 415)
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    if len(text) < 20:
        raise IngestError("No extractable text found (scanned PDF?). Nothing was saved.")
    return text


def guess_date(text: str, filename: str) -> str:
    for src in (filename, text[:600]):
        m = _DATE.search(src)
        if m:
            return m.group(0)
        m = _LONG_DATE.search(src)
        if m:
            return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return date.today().isoformat()


def ingest_note(store: DocumentStore, client_id: str, filename: str, data: bytes) -> MeetingNoteDoc:
    if store.get_client(client_id) is None:
        raise IngestError("Unknown client.", 404)
    text = extract_text(filename, data)
    title = re.sub(r"\.[^.]+$", "", filename.rsplit("/", 1)[-1]).replace("_", " ").replace("-", " ").strip() or "Uploaded note"
    note = MeetingNoteDoc(
        id=f"{UPLOAD_ID_PREFIX}{int(time.time() * 1000)}", client_id=client_id, date=guess_date(text, filename),
        title=title, source_file=filename, text=text,
    )
    return store.add_note(note)
