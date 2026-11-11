import os
import sqlite3
import time
import json
from typing import List, Dict, Optional

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "enchanted_diary.db")

class BoardStorage:
    """
    Manages SQLite persistence for whiteboard boards, objects, and metadata.
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_tables()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Whiteboard boards table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS whiteboard_boards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                data_json TEXT NOT NULL,
                thumbnail TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        # Seed default board if table is empty
        cursor.execute("SELECT COUNT(*) FROM whiteboard_boards")
        if cursor.fetchone()[0] == 0:
            now = time.time()
            default_board = {
                "version": "1.0",
                "objects": []
            }
            cursor.execute("""
                INSERT INTO whiteboard_boards (id, name, data_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, ("default", "Main Whiteboard", json.dumps(default_board), now, now))
        
        conn.commit()
        conn.close()

    def save_board(self, board_id: str, name: str, data_json: str, thumbnail: Optional[str] = None) -> bool:
        try:
            now = time.time()
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO whiteboard_boards (id, name, data_json, thumbnail, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    data_json = excluded.data_json,
                    thumbnail = COALESCE(excluded.thumbnail, whiteboard_boards.thumbnail),
                    updated_at = excluded.updated_at
            """, (board_id, name, data_json, thumbnail, now, now))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[BoardStorage] Error saving board {board_id}: {e}")
            return False

    def get_board(self, board_id: str) -> Optional[Dict]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM whiteboard_boards WHERE id = ?", (board_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "data": json.loads(row["data_json"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            return None
        except Exception as e:
            print(f"[BoardStorage] Error retrieving board {board_id}: {e}")
            return None

    def list_boards(self) -> List[Dict]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, created_at, updated_at FROM whiteboard_boards ORDER BY updated_at DESC")
            rows = cursor.fetchall()
            conn.close()
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"]
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[BoardStorage] Error listing boards: {e}")
            return []

    def delete_board(self, board_id: str) -> bool:
        if board_id == "default":
            return False  # Prevent deleting default board
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM whiteboard_boards WHERE id = ?", (board_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[BoardStorage] Error deleting board {board_id}: {e}")
            return False
