import sqlite3
import hashlib
import os
import threading
from src.config import DB_PATH

_db_lock = threading.Lock()

def _get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS translations (
            hash_id TEXT PRIMARY KEY,
            translated_text TEXT
        )
    ''')
    conn.commit()
    return conn

_conn = _get_connection()

def _get_hash(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def get_cached_translation(original_text: str) -> str:
    with _db_lock:
        cursor = _conn.cursor()
        cursor.execute('SELECT translated_text FROM translations WHERE hash_id = ?', (_get_hash(original_text),))
        row = cursor.fetchone()
        return row[0] if row else None

def save_translation(original_text: str, translated_text: str):
    with _db_lock:
        try:
            cursor = _conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO translations (hash_id, translated_text)
                VALUES (?, ?)
            ''', (_get_hash(original_text), translated_text))
            _conn.commit()
        except Exception as e:
            print(f"\n[WARNING] Failed to save to cache DB: {e}")

def close_and_clear_cache():
    """Closes the connection and deletes the DB file upon success."""
    with _db_lock:
        _conn.close()
        try:
            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)
        except Exception:
            pass
