from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import datetime

# Regulation Schemas
class RegulationUploadResponse(BaseModel):
    regulation_id: int
    title: str
    version_label: str
    page_count: int
    message: str

class ParsedPageBlock(BaseModel):
    page_number: int
    text_block: str

class ParsedDocument(BaseModel):
    file_path: str
    pages: List[ParsedPageBlock]
