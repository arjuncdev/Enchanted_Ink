import os
import sqlite3
import time
import math
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "enchanted_diary.db")

class EpisodicMemoryEngine:
    """
    Episodic Memory & Forgetting Engine based on:
      - Zhong et al. (AAAI 2024) [MemoryBank / Ebbinghaus Forgetting Curve]
      - Park et al. (ACM UIST 2023) [Generative Agents Memory Scoring]
      - Cheng et al. (ACL 2024) [TiM Knowledge Triples]
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_database()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Pages and turns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_number INTEGER NOT NULL,
                user_text TEXT,
                ai_reply TEXT,
                confidence REAL,
                persona TEXT DEFAULT 'tom_riddle',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Episodic propositions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                summary TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at REAL NOT NULL,
                last_accessed_at REAL NOT NULL
            )
        """)
        
        # Seed initial autobiographical memories if empty
        cursor.execute("SELECT COUNT(*) FROM memories")
        if cursor.fetchone()[0] == 0:
            now = time.time()
            initial_memories = [
                ("User", "possesses", "a mysterious digital diary bound in worn dark leather", "User holds this enchanted book.", 0.9, now - 86400 * 3),
                ("User", "confided", "feelings of deep curiosity about secrets kept within the parchment", "User seeks the spirit within.", 0.8, now - 86400 * 2),
                ("Diary Spirit", "recollects", "memories that sleep like shadows until awakened by the quill", "The diary honors memories across time.", 0.85, now - 86400 * 1),
            ]
            for subj, pred, obj, summ, imp, ts in initial_memories:
                cursor.execute("""
                    INSERT INTO memories (subject, predicate, object, summary, importance, created_at, last_accessed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (subj, pred, obj, summ, imp, ts, ts))
        
        conn.commit()
        conn.close()

    def calculate_ebbinghaus_salience(self, created_at: float, importance: float, half_life_days: float = 7.0) -> float:
        """
        Ebbinghaus temporal retention decay:
        R(t) = exp(-lambda * delta_t) * importance
        where lambda = ln(2) / half_life_days
        """
        now = time.time()
        delta_days = (now - created_at) / (24 * 3600)
        decay_constant = math.log(2) / max(half_life_days, 1.0)
        retention = math.exp(-decay_constant * delta_days)
        return round(float(retention * importance), 3)

    def extract_and_store_proposition(self, user_text: str):
        """
        Extracts atomic propositions from user text and commits them to memory.
        Robustly handles edge cases, formatting variances, and errors.
        """
        if not user_text or len(user_text.strip()) < 3:
            return

        try:
            import re
            user_clean = user_text.strip()
            user_lower = user_clean.lower()
            now = time.time()
            conn = self._get_connection()
            cursor = conn.cursor()

            # Name statement: "My name is John" or "I am Alice"
            match_name = re.search(r"(?:my name is|i am called|i am)\s+([a-zA-Z0-9\s]+)", user_clean, re.IGNORECASE)
            # Emotion: "I feel sad" or "I felt happy"
            match_feel = re.search(r"(?:i feel|i felt|feeling)\s+([a-zA-Z0-9\s]+)", user_clean, re.IGNORECASE)
            # Preference: "I like books" or "I love magic"
            match_love = re.search(r"(?:i like|i love|i cherish)\s+([a-zA-Z0-9\s]+)", user_clean, re.IGNORECASE)

            if match_name and len(match_name.group(1).strip()) > 1:
                name_val = match_name.group(1).strip().strip(".!?,")
                cursor.execute("""
                    INSERT INTO memories (subject, predicate, object, summary, importance, created_at, last_accessed_at)
                    VALUES ('User', 'is called', ?, ?, 0.95, ?, ?)
                """, (name_val, f"User's name is {name_val}.", now, now))
            elif match_feel and len(match_feel.group(1).strip()) > 1:
                feeling = match_feel.group(1).strip().strip(".!?,")
                cursor.execute("""
                    INSERT INTO memories (subject, predicate, object, summary, importance, created_at, last_accessed_at)
                    VALUES ('User', 'felt', ?, ?, 0.75, ?, ?)
                """, (feeling, f"User confessed feeling: {feeling}.", now, now))
            elif match_love and len(match_love.group(1).strip()) > 1:
                pref = match_love.group(1).strip().strip(".!?,")
                cursor.execute("""
                    INSERT INTO memories (subject, predicate, object, summary, importance, created_at, last_accessed_at)
                    VALUES ('User', 'cherishes', ?, ?, 0.70, ?, ?)
                """, (pref, f"User cherishes {pref}.", now, now))
            else:
                # General episodic proposition
                summary = f"User inscribed: '{user_clean[:60]}'."
                cursor.execute("""
                    INSERT INTO memories (subject, predicate, object, summary, importance, created_at, last_accessed_at)
                    VALUES ('User', 'inquired / wrote', ?, ?, 0.50, ?, ?)
                """, (user_clean[:80], summary, now, now))

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[MemoryEngine] Proposition extraction non-critical error: {e}")

    def retrieve_relevant_memories(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        Retrieves top-k episodic memories ranked by a tri-factor score:
        Score = 0.5 * SemanticRelevance + 0.3 * EbbinghausDecay + 0.2 * Importance
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories ORDER BY created_at DESC")
        rows = cursor.fetchall()
        
        query_words = set(query.lower().split())
        scored_memories = []

        now = time.time()
        for r in rows:
            summary = r["summary"].lower()
            subject = r["subject"].lower()
            predicate = r["predicate"].lower()
            obj = r["object"].lower()
            text_corpus = f"{summary} {subject} {predicate} {obj}"

            # Keyword lexical overlap matching
            overlap = sum(1 for w in query_words if len(w) > 2 and w in text_corpus)
            semantic_sim = min(overlap / max(len(query_words), 1), 1.0)
            
            # Ebbinghaus decay
            decay_score = self.calculate_ebbinghaus_salience(r["created_at"], r["importance"])
            
            # Tri-factor ranking score
            total_score = (0.5 * semantic_sim) + (0.3 * decay_score) + (0.2 * r["importance"])

            scored_memories.append({
                "id": r["id"],
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "summary": r["summary"],
                "importance": r["importance"],
                "salience": decay_score,
                "score": round(total_score, 3),
                "created_at_iso": datetime.fromtimestamp(r["created_at"], timezone.utc).strftime("%Y-%m-%d %H:%M")
            })

        scored_memories.sort(key=lambda m: m["score"], reverse=True)
        conn.close()
        return scored_memories[:top_k]

    def list_all_memories(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories ORDER BY created_at DESC")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            salience = self.calculate_ebbinghaus_salience(r["created_at"], r["importance"])
            result.append({
                "id": r["id"],
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "summary": r["summary"],
                "importance": r["importance"],
                "salience_pct": int(salience * 100),
                "created_at_iso": datetime.fromtimestamp(r["created_at"], timezone.utc).strftime("%Y-%m-%d %H:%M")
            })
        conn.close()
        return result

    def delete_memory(self, memory_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        return rows_affected > 0

    def purge_all_memories(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memories")
        cursor.execute("DELETE FROM pages")
        conn.commit()
        conn.close()

    def record_page_turn(self, page_number: int, user_text: str, ai_reply: str, confidence: float, persona: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pages (page_number, user_text, ai_reply, confidence, persona)
            VALUES (?, ?, ?, ?, ?)
        """, (page_number, user_text, ai_reply, confidence, persona))
        conn.commit()
        conn.close()

    def get_page_history(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pages ORDER BY page_number ASC")
        rows = cursor.fetchall()
        result = [dict(r) for r in rows]
        conn.close()
        return result
