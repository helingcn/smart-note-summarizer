import ollama

def summarize_text(text, model="qwen2.5:7b"):
    prompt = f"Summerize the key points of the following text:\n\n{text}"
    response = ollama.chat(model=model, messages=[
        {"role": "user" , "content": prompt}])
    return response["message"]["content"]

def split_text(text, chunk_size=3000):
    chunks = []
    for i in range (0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks

def summarize_long_text(text, model="qwen2.5:7b", chunk_size=3000):
    if len(text) <= chunk_size:
        return summarize_text(text, model=model)

    chunks =split_text(text, chunk_size)
    partial_summaries = []
    for chunk in chunks:
        partial_summary = summarize_text(chunk, model=model)
        partial_summaries.append(partial_summary)

    combined = "\n".join(partial_summaries)
    final_summary = summarize_text(combined, model=model)
    return final_summary
    