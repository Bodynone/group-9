"""Immutable course documents, bounded extraction and codepoint-scoped BM25 retrieval."""

from collections import Counter
import base64
import hashlib
import io
import math
from pathlib import PurePath
import re
import xml.etree.ElementTree as ET
import zipfile

from .schemas_v2 import V2Error

MAX_FILE = 2_000_000
MAX_TEXT = 100_000


def extract(filename, encoded):
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise V2Error("DOCUMENT_INVALID", "文件编码不合法", 422) from None
    if not data or len(data) > MAX_FILE:
        raise V2Error("DOCUMENT_LIMIT", "资料文件须为1至2000000字节", 413)
    suffix = PurePath(filename).suffix.lower()
    try:
        if suffix in (".txt", ".md"):
            text = data.decode("utf-8")
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                if sum(x.file_size for x in package.infolist()) > 10_000_000:
                    raise ValueError("unpacked document too large")
                raw = package.read("word/document.xml")
                declarations = raw.replace(b"\x00", b"").upper()
                if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
                    raise ValueError("entities are unsupported")
                root = ET.fromstring(raw)
                ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                text = "\n".join("".join((e.text or "") if e.tag == ns + "t" else "\t" if e.tag == ns + "tab" else "\n" if e.tag in (ns + "br", ns + "cr") else ""
                                                for e in paragraph.iter()) for paragraph in root.iter(ns + "p"))
        elif suffix == ".pdf":
            from pypdf import PdfReader, apply_configuration
            # Context-local parser bounds also cover decompression and nested content.
            with apply_configuration(zlib_maximum_output_length=4_000_000, maximum_declared_stream_length=4_000_000,
                                     stream_decoding_work_maximum_length=12_000_000, stream_parsing_work_maximum_count=200000,
                                     page_tree_maximum_entries=1000, xform_maximum_invocations_per_extraction=100):
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted or len(reader.pages) > 30:
                    raise ValueError("encrypted or more than 30 pages")
                parts = []
                for page in reader.pages:
                    stream = page.get_contents()
                    if stream is not None and len(stream.get_data()) > 4_000_000:
                        raise ValueError("page content too large")
                    parts.append(page.extract_text() or "")
                    if sum(len(p) for p in parts) > MAX_TEXT:
                        raise ValueError("extracted text too large")
                text = "\n\f\n".join(parts)
        else:
            raise V2Error("DOCUMENT_FORMAT", "课程资料支持UTF-8 TXT/MD、DOCX和文本PDF", 422)
    except V2Error:
        raise
    except Exception:
        raise V2Error("DOCUMENT_INVALID", "无法解析资料，请检查格式、加密、页数及大小；扫描件须先转换为文本", 422) from None
    if not text.strip() or len(text) > MAX_TEXT:
        raise V2Error("DOCUMENT_LIMIT", "提取文本须为1至100000字符，不支持纯扫描图片", 422)
    return text, hashlib.sha256(data).hexdigest()


def chunks(text, size=900, overlap=100):
    """Offsets always refer to unmodified extracted text, including BOM and emoji."""
    result, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary + 1
        result.append({"start": start, "end": end, "quote": text[start:end], "chunk_id": f"{start}:{end}"})
        if end == len(text):
            break
        start = end - overlap
    return result


def tokens(text):
    terms = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.lower())
    return [token for term in terms for token in ([term] if not re.fullmatch(r"[\u3400-\u9fff]+", term) or len(term) == 1
                                                else [term[i:i + 2] for i in range(len(term) - 1)])]


def retrieve(documents, query, limit=3):
    """Local lexical BM25, not embeddings. Zero overlap returns no invented sources."""
    corpus = [{**part, "document_id": doc["id"], "title": doc["title"], "content_hash": doc["content_hash"]}
              for doc in documents for part in chunks(doc["text"])]
    bags = [Counter(tokens(row["quote"])) for row in corpus]
    lengths = [sum(bag.values()) for bag in bags]
    average = sum(lengths) / len(lengths) if lengths else 1
    query_tokens = set(tokens(query))
    frequency = {term: sum(term in bag for bag in bags) for term in query_tokens}
    matches = []
    for row, bag, length in zip(corpus, bags, lengths):
        score = sum(math.log(1 + (len(corpus) - frequency[term] + .5) / (frequency[term] + .5)) * bag[term] * 2.5 /
                    (bag[term] + 1.5 * (.25 + .75 * length / (average or 1))) for term in query_tokens if bag[term])
        if score > 0:
            matches.append({**row, "retrieval_score": round(score, 6)})
    return sorted(matches, key=lambda x: (-x["retrieval_score"], x["document_id"], x["start"]))[:limit]


def unique_passages(matches):
    """Transmit shared passages once while retaining each dimension's source links."""
    seen = {}
    for match in matches:
        key = match["document_id"] + "/" + match["chunk_id"]
        seen.setdefault(key, {**match, "passage_id": key})
    return list(seen.values())
