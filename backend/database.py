import sqlite3

DB_PATH = "smartdigest.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_text TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_summary(original_text , summary):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("INSERT INTO summaries (original_text, summary) VALUES (?,?)",
                   (original_text, summary)
    )
    conn.commit()
    conn.close()

def get_history():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id ,original_text , summary, created_at FROM summaries ORDER BY created_at DESC")
    rows = cursor.fetchall()

    conn.close()
    return rows
                   
