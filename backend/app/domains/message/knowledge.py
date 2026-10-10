"""AI 客服资料：从上传的文件里提取纯文本，并按买家问题挑选相关段落。"""

import asyncio
import io
import zipfile
from pathlib import PurePath

from app.intelligence.retrieval import select_knowledge

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_DOC_CHARS = 1_000_000  # 单份资料保存的最大字数（超出部分截断）；回复时只取相关段落，不受总长影响
DOCS_IN_PROMPT_CHARS = 1500  # 每次回复从资料里最多带入的字数
SUPPORTED = (".txt", ".md", ".csv", ".pdf", ".docx")
MAX_PDF_PAGES = 3000
MAX_DOCX_UNZIPPED = 300 * 1024 * 1024  # 防压缩炸弹：docx 解压后的总大小上限
PARSE_TIMEOUT = 90  # 秒
_parse_slots = asyncio.Semaphore(2)  # 同时最多解析 2 份，避免大文件占满 CPU


class UnsupportedFile(ValueError):
    pass


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def extract_text(filename: str, data: bytes) -> str:
    """支持 txt / md / csv / pdf / docx；扫描版 PDF（图片）提取不到文字时报错。"""
    if len(data) > MAX_FILE_BYTES:
        raise UnsupportedFile("文件超过 50MB，请拆分后再上传")
    ext = PurePath(filename).suffix.lower()
    if ext in (".txt", ".md", ".csv"):
        text = _decode(data)
    elif ext == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise UnsupportedFile(f"PDF 超过 {MAX_PDF_PAGES} 页，请拆分后再上传")
            parts: list[str] = []
            total = 0
            for page in reader.pages:
                t = (page.extract_text() or "").strip()
                parts.append(t)
                total += len(t)
                if total > MAX_DOC_CHARS:  # 字数够了就不再解析后面的页
                    break
            text = "\n\n".join(parts)
        except (PdfReadError, ValueError) as e:
            if isinstance(e, UnsupportedFile):
                raise
            raise UnsupportedFile("PDF 无法读取，可能已加密或损坏") from e
    elif ext == ".docx":
        from docx import Document

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_DOCX_UNZIPPED:
                    raise UnsupportedFile("Word 文件解压后过大，请精简后再上传")
        except zipfile.BadZipFile as e:
            raise UnsupportedFile("Word 文件无法读取，请另存为 .docx 后重试") from e
        try:
            doc = Document(io.BytesIO(data))
        except Exception as e:  # noqa: BLE001  python-docx 对损坏文件抛出的异常类型不固定
            raise UnsupportedFile("Word 文件无法读取，请另存为 .docx 后重试") from e
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:  # 价目表等常写在表格里
            for row in table.rows:
                lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        text = "\n".join(lines)
    else:
        raise UnsupportedFile(f"暂不支持该格式，请上传 {' / '.join(SUPPORTED)}")
    text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines()).strip()
    if not text:
        raise UnsupportedFile("没有从文件里读到文字（扫描版 PDF 需要先转成文字）")
    return text[:MAX_DOC_CHARS]


async def extract_text_async(filename: str, data: bytes) -> str:
    """在后台线程里解析（不阻塞事件循环：否则解析大 PDF 时收消息、自动回复、发货都会停住），
    限制并发与时长。"""
    async with _parse_slots:
        try:
            return await asyncio.wait_for(asyncio.to_thread(extract_text, filename, data), PARSE_TIMEOUT)
        except TimeoutError as e:
            raise UnsupportedFile("文件解析超时，请拆分或转成 txt 后再上传") from e


def select_from_docs(docs: list[tuple[str, str]], query: str, max_chars: int = DOCS_IN_PROMPT_CHARS) -> str:
    """docs 为 (文件名, 内容)。资料总量不大时全部带上，否则按相关度挑段落。"""
    if not docs:
        return ""
    joined = "\n\n".join(f"《{name}》\n{content}" for name, content in docs)
    return select_knowledge(joined, query, max_chars=max_chars)
