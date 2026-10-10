"""AI 客服资料：从上传的文件里提取纯文本，并按买家问题挑选相关段落。"""

import io
from pathlib import PurePath

from app.intelligence.retrieval import select_knowledge

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DOC_CHARS = 200_000  # 单份资料保存的最大字数（超出部分截断）
DOCS_IN_PROMPT_CHARS = 1500  # 每次回复从资料里最多带入的字数
SUPPORTED = (".txt", ".md", ".csv", ".pdf", ".docx")


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
        raise UnsupportedFile("文件超过 5MB，请拆分后再上传")
    ext = PurePath(filename).suffix.lower()
    if ext in (".txt", ".md", ".csv"):
        text = _decode(data)
    elif ext == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        except (PdfReadError, ValueError) as e:
            raise UnsupportedFile("PDF 无法读取，可能已加密或损坏") from e
    elif ext == ".docx":
        from docx import Document

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


def select_from_docs(docs: list[tuple[str, str]], query: str, max_chars: int = DOCS_IN_PROMPT_CHARS) -> str:
    """docs 为 (文件名, 内容)。资料总量不大时全部带上，否则按相关度挑段落。"""
    if not docs:
        return ""
    joined = "\n\n".join(f"《{name}》\n{content}" for name, content in docs)
    return select_knowledge(joined, query, max_chars=max_chars)
