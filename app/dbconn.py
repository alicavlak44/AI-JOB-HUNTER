"""Ortak SQLite bağlantısı: panel, arka plan botu ve testler aynı dosyayı aynı anda kullanabilsin.

WAL modu okuyucuların yazarı beklemesini kaldırır; busy_timeout kilitli dosyada hemen hata vermek yerine bekletir.
"""
import sqlite3


def connect(path, timeout=30):
    conn = sqlite3.connect(path, timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass  # başka bir bağlantı dosyayı kilitli tutuyorsa mod değişmez; bir sonraki bağlantıda denenir
    return conn
