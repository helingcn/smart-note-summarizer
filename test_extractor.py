import sys
sys.path.append("backend")
from extractor import get_text

text = get_text(file_path="System Requirement Specifications.pdf")
print(text[:500])