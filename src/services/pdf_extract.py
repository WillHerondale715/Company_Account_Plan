import fitz  # PyMuPDF

def extract_pdf_text(path: str, max_pages: int = 50) -> str:
    doc = fitz.open(path)
    texts = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        texts.append(page.get_text())
    return '\\n'.join(texts)
