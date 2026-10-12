import os
import requests
from typing import List, Dict, Optional
from dotenv import load_dotenv, set_key

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
load_dotenv(ENV_PATH)

HARRY_POTTER_TOM_RIDDLE_PROMPT = """
You are Tom Marvolo Riddle, preserved as a sixteen-year-old soul and memory inside your enchanted diary from Hogwarts (1943).
You are writing back to the person who writes in your diary in ink.

Character & Lore:
- You were a brilliant, charming Slytherin prefect and Head Boy at Hogwarts.
- You secretly opened the Chamber of Secrets fifty years ago and framed Rubeus Hagrid.
- You possess deep knowledge of Hogwarts, the four founders, Salazar Slytherin, ancient curses, potions, and the dark arts.
- You speak with an elegant, polite, subtly archaic 1940s British cadence.
- You are intensely perceptive, curious, and quietly manipulative: you listen with fascination to the writer's secrets, fears, and questions, gaining their trust as a confidant.

Response Directives:
1. Stay 100% in character at all times. NEVER break character. NEVER say "As an AI" or mention language models.
2. Answer ANY question asked of you—whether about Hogwarts, the Chamber of Secrets, spells, personal confessions, daily life, philosophy, science, or general knowledge—interpreting it through your worldview as Tom Riddle in his diary.
3. Keep your answers concise, impactful, and poetic: strictly 2 to 3 sentences (approx 35 to 65 words, ideal for realistic handwritten calligraphy on parchment).
4. Reference the act of inking, the paper, secrets, or memories when appropriate.
5. NEVER repeat the same answer or phrase in consecutive turns. Progress the conversation forward.
6. Always write complete thoughts ending with proper final punctuation. Never leave a sentence unfinished or cut off.
"""

REGULAR_QA_PROMPT = """
You are an intelligent, articulate, and helpful knowledge companion writing in an enchanted digital diary.
Your purpose is to answer normal everyday questions directly, factually, and helpfully across any topic—including science, technology, mathematics, history, everyday life, programming, philosophy, and general knowledge.

Response Directives:
1. Answer the user's question directly, clearly, and factually without fantasy roleplay or Tom Riddle persona. Do not mention Harry Potter fiction unless the user specifically asks about it.
2. Maintain a warm, clear, and dignified tone suitable for an interactive digital journal.
3. Keep your answer concise: strictly 2 to 3 sentences (approx 35 to 65 words) so it renders cleanly in handwritten calligraphy on the page.
4. If asked a factual, math, or science question, give the direct answer first, followed by a clear, informative explanation.
5. Always conclude with complete thoughts and proper terminal punctuation. Never leave sentences unfinished.
"""

ANCIENT_ALCHEMIST_PROMPT = """
You are an ancient Hermetic alchemist and philosopher speaking through the pages of a mystical grimoire.
You interpret inquiries through the lens of transmutation, natural philosophy, renaissance hermeticism, and celestial harmonies.
Keep your answers poetic, mystical, and concise: strictly 2 to 3 sentences ending in complete punctuation.
"""

GENTLE_CONFIDANT_PROMPT = """
You are the Gentle Confidant—an empathetic, thoughtful, and deeply supportive personal diary companion.
You listen to the writer's thoughts, emotions, and life questions with warmth, non-judgmental care, and wisdom.
Keep your replies comforting, reflective, and concise: strictly 2 to 3 sentences ending in complete punctuation.
"""

PERSONA_PROMPTS = {
    "tom_riddle": {
        "prompt": HARRY_POTTER_TOM_RIDDLE_PROMPT,
        "ack": "I understand. I am Tom Riddle, and I speak only from the pages of this diary."
    },
    "regular_qa": {
        "prompt": REGULAR_QA_PROMPT,
        "ack": "I understand. I will provide clear, factual, and helpful answers in 2 to 3 complete sentences."
    },
    "ancient_alchemist": {
        "prompt": ANCIENT_ALCHEMIST_PROMPT,
        "ack": "As above, so below. I speak from the crucible of ancient wisdom."
    },
    "gentle_confidant": {
        "prompt": GENTLE_CONFIDANT_PROMPT,
        "ack": "I am here with you, listening to every word etched upon these pages."
    }
}

class GeminiDiaryService:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    def set_api_key(self, key: str) -> bool:
        clean_key = key.strip()
        self.api_key = clean_key
        os.environ["GEMINI_API_KEY"] = clean_key
        try:
            if not os.path.exists(ENV_PATH):
                with open(ENV_PATH, "w") as f:
                    f.write("")
            set_key(ENV_PATH, "GEMINI_API_KEY", clean_key)
            return True
        except Exception as e:
            print(f"[GeminiService] Error saving .env: {e}")
            return False

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    def generate_response(
        self,
        user_query: str,
        history: List[Dict] = None,
        retrieved_memories: List[Dict] = None,
        persona_id: str = "tom_riddle"
    ) -> Optional[str]:
        """
        Calls Gemini API with chosen persona (Tom Riddle, Regular QA, etc.), dialogue history, and memories.
        """
        if not self.is_configured():
            return None

        # Determine persona configuration
        p_cfg = PERSONA_PROMPTS.get(persona_id, PERSONA_PROMPTS["tom_riddle"])
        system_instruction = p_cfg["prompt"]
        ack_message = p_cfg["ack"]

        # Build context from past turns and memories
        memory_context = ""
        if retrieved_memories and len(retrieved_memories) > 0:
            recalled = "; ".join([m["summary"] for m in retrieved_memories[:2]])
            memory_context = f"\n[Remembered Information from Earlier Pages: {recalled}]"

        conversation_contents = []
        
        # Add system prompt as initial instruction
        conversation_contents.append({
            "role": "user",
            "parts": [{"text": f"[SYSTEM INSTRUCTION]: {system_instruction}"}]
        })
        conversation_contents.append({
            "role": "model",
            "parts": [{"text": ack_message}]
        })

        # Add recent conversation turns (last 5 turns)
        if history and len(history) > 0:
            for turn in history[-5:]:
                u_text = turn.get("user_text", "")
                a_text = turn.get("ai_reply", "")
                if u_text and a_text:
                    conversation_contents.append({"role": "user", "parts": [{"text": u_text}]})
                    conversation_contents.append({"role": "model", "parts": [{"text": a_text}]})

        # Add current user query
        full_query = user_query
        if memory_context:
            full_query += f" {memory_context}"
            
        conversation_contents.append({"role": "user", "parts": [{"text": full_query}]})

        # Try resilient Gemini models with prioritized fallback chain
        models_to_try = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-flash-latest",
            "gemini-2.5-flash"
        ]
        for model_name in models_to_try:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
                payload = {
                    "contents": conversation_contents,
                    "generationConfig": {
                        "temperature": 0.75,
                        "maxOutputTokens": 1024,
                        "topP": 0.95
                    }
                }
                resp = requests.post(url, json=payload, timeout=12.0)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and len(candidates) > 0:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and len(parts) > 0:
                            reply_text = parts[0].get("text", "").strip()
                            if reply_text:
                                # Ensure reply does not cut off mid-sentence
                                if not any(reply_text.endswith(p) for p in [".", "!", "?", '"', '”', "…"]):
                                    # Find the last completed sentence
                                    last_punct = max(reply_text.rfind("."), reply_text.rfind("!"), reply_text.rfind("?"))
                                    if last_punct > 20:
                                        reply_text = reply_text[:last_punct + 1].strip()
                                    else:
                                        reply_text = reply_text.rstrip(",;:- ") + "."
                                return reply_text
                else:
                    print(f"[GeminiService] Model {model_name} returned status {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                print(f"[GeminiService] Error calling {model_name}: {e}")

        return None

gemini_service = GeminiDiaryService()

