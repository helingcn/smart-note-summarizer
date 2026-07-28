import pdfplumber

def extract_text_from_pdf(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def get_text(file_path=None,  raw_text=None):
    if file_path:
        return extract_text_from_pdf(file_path)
    elif raw_text:
        return raw_text
    else: 
        raise ValueError("No PDF file or text was provided")
