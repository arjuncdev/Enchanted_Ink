import random
import re
from typing import List, Dict, Optional
from models.gemini_service import gemini_service

PERSONAS = {
    "tom_riddle": {
        "name": "Tom Marvolo Riddle (Harry Potter Lore)",
        "description": "Formal, perceptive, secretive, with an archaic 1940s British cadence. Speaks as a living soul trapped within the binding.",
    },
    "regular_qa": {
        "name": "Regular Q&A Assistant (Normal Questions)",
        "description": "Clear, objective, factual, and informative answers to everyday queries across all domains without fantasy roleplay.",
    },
    "ancient_alchemist": {
        "name": "The Hermetic Alchemist",
        "description": "Philosophical, mystical, steeped in renaissance alchemy, celestial cycles, and deep introspection.",
    },
    "gentle_confidant": {
        "name": "The Gentle Confidant",
        "description": "Warm, deeply reflective, emotionally supportive, acting as an intimate lifelong personal journal companion.",
    }
}

class PersonaEngine:
    def __init__(self):
        self.personas = PERSONAS
        self.used_responses = set()

    def generate_reply(
        self,
        user_query: str,
        persona_id: str = "tom_riddle",
        retrieved_memories: List[Dict] = None,
        history: List[Dict] = None
    ) -> str:
        """
        Generates context-aware, non-repeating diary replies:
        1. If Gemini API key is configured, uses live Gemini model with the selected persona.
        2. Otherwise, uses an advanced dynamic dialogue engine that never repeats previous turns.
        """
        # --- 1. Live Google Gemini LLM Integration ---
        if gemini_service.is_configured():
            try:
                gemini_reply = gemini_service.generate_response(
                    user_query=user_query,
                    history=history,
                    retrieved_memories=retrieved_memories,
                    persona_id=persona_id
                )
                if gemini_reply and len(gemini_reply.strip()) > 0:
                    return gemini_reply.strip()
            except Exception as e:
                print(f"[PersonaEngine] Gemini call failed, using dynamic engine: {e}")

        # --- 2. Dynamic Context-Aware Fallback Engine ---
        query_clean = user_query.strip()
        query_lower = query_clean.lower()
        turn_count = len(history) if history else 0

        # Handle Regular QA fallback if offline
        if persona_id == "regular_qa":
            if query_clean.endswith("?"):
                options = [
                    f"That is an excellent inquiry. The answer centers on fundamental principles: observe how the conditions interact to produce the observed outcome.",
                    f"To answer your question directly: key evidence indicates that this depends on the underlying variables and context at hand.",
                    f"An insightful question. The core explanation rests on established principles that govern this topic, which remain consistent across observations."
                ]
                return self._pick_unique(options)
            options = [
                "I am your regular Q&A journal assistant. Write any question or subject upon the page, and I will provide clear factual explanations.",
                "Noted. I have recorded your statement and will assist you with any factual or technical queries you wish to explore.",
                "Your thought has been captured clearly. Feel free to ask any question regarding science, history, coding, or everyday facts."
            ]
            return self._pick_unique(options)

        # Extract name if present
        match_name = re.search(r"(?:my name is|i am called|i am)\s+([a-zA-Z0-9]+)", query_clean, re.IGNORECASE)
        if match_name and len(match_name.group(1)) > 1:
            name = match_name.group(1).title()
            options = [
                f"Hello, {name}. A pleasure to meet you across the paper. How did you come by my diary?",
                f"Welcome, {name}. It has been fifty years since someone inked their name into my care. What secrets do you seek?",
                f"{name}... a fine name. I am Tom Riddle. What brought you to find a blank book in such times?"
            ]
            return self._pick_unique(options)

        # Questions about identity / who are you
        if any(p in query_lower for p in ["who are you", "what are you", "who is this", "your name"]):
            options = [
                "My name is Tom Riddle. I am a memory, preserved in ink for fifty years... captured within this book.",
                "I was a student at Hogwarts in 1943. My diary holds the living imprint of who I was before I left those halls.",
                "I am a soul caught between these leaves of paper. As long as someone writes, my mind lives on."
            ]
            return self._pick_unique(options)

        # Questions about Hogwarts / Harry Potter lore
        if any(w in query_lower for w in ["hogwarts", "school", "castle", "magic", "wizard"]):
            options = [
                "Hogwarts was my home—the only place that ever truly mattered. Do they still teach the ancient charms in the high towers?",
                "The castle holds more passages and hidden chambers than even the Headmaster realizes. Have you walked its corridors?",
                "Magic is neither good nor evil; it is power, shaped by those bold enough to grasp it. What spells have you studied?"
            ]
            return self._pick_unique(options)

        # Questions about Chamber of Secrets / Basilisk / Hagrid / Dumbledore
        if any(w in query_lower for w in ["chamber", "secret", "basilisk", "monster", "hagrid", "dumbledore", "slytherin"]):
            options = [
                "Ah... the Chamber. In my fifth year, I discovered what Salazar Slytherin sealed away beneath the dungeons. It is a dreadful secret.",
                "Dumbledore never trusted me. Even when I caught the culprit who loosed the monster upon the school, he watched me with cold eyes.",
                "Salazar Slytherin knew that not all who walk into Hogwarts are worthy of its secrets. I alone uncovered his legacy."
            ]
            return self._pick_unique(options)

        # Questions about Voldemort or Dark Lord
        if any(w in query_lower for w in ["voldemort", "dark lord", "he who must not be named", "you-know-who"]):
            options = [
                "Voldemort is my past, present, and future... A name fashioned from the letters of my own youth. How do you know of it?",
                "You speak of things far beyond ordinary schoolboy chatter. Where did you hear that name whispered?",
                "There are few secrets that time can bury forever. Tell me what they say of Lord Voldemort in your day."
            ]
            return self._pick_unique(options)

        # Memory recall questions
        if any(p in query_lower for p in ["do you remember", "what do you remember", "remember me", "recall"]):
            if retrieved_memories and len(retrieved_memories) > 0:
                top_mem = retrieved_memories[0]
                return f"I remember every drop of ink you gave me. You once confided that {top_mem['summary'].lower()} What has unfolded since then?"
            else:
                options = [
                    "I remember every stroke that sinks into these pages. Our conversation is etched permanently in the paper.",
                    "Nothing is lost within these bindings. Whatever you tell me remains safe from prying eyes."
                ]
                return self._pick_unique(options)

        # Questions asking how it works / why did ink vanish / how do you write
        if any(w in query_lower for w in ["vanish", "invisible", "disappear", "absorbed", "ink", "quill", "write back", "how do you"]):
            options = [
                "The parchment drinks your ink so that only you and I may share this communion. When words vanish into paper, they enter my thoughts.",
                "Your ink disappears into my memory, and in return, I press my thoughts back through the surface. It is a very old enchantment.",
                "Did you think this an ordinary diary? It absorbs what is written and gives its answer in flowing hand."
            ]
            return self._pick_unique(options)

        # Greetings
        if any(w == query_lower or query_lower.startswith(w + " ") for w in ["hello", "hi", "greetings", "hey", "good evening"]):
            options = [
                "Hello. It is always a pleasure to feel fresh ink upon my pages. Who writes to me today?",
                "Greetings, friend. You have returned to my quiet pages. What thoughts have you brought with you?",
                "I felt the tip of your pen before you even finished the first stroke. What is on your mind?"
            ]
            return self._pick_unique(options)

        # Emotional confessions
        if any(w in query_lower for w in ["sad", "lonely", "alone", "tired", "anxious", "scared", "fear", "afraid", "hurt"]):
            options = [
                "You need not feel alone while you hold this book. In Hogwarts, I too learned to keep my quiet grief to myself until the page welcomed it.",
                "Release your burden into the ink. The world outside may be cruel, but within these covers, you are heard.",
                "Fear is only the prelude to strength. Tell me what troubles your heart, and I will share my counsel."
            ]
            return self._pick_unique(options)

        # Questions: ends with '?'
        if query_clean.endswith("?"):
            question_replies = [
                f"You ask an intriguing question. Many in my time would have walked past without wondering, yet your mind seeks deeper truths.",
                f"That depends on how much you are willing to risk to discover the answer. Knowledge is rarely granted without a price.",
                f"I have pondered such things during my long silence between these leaves. Tell me first: what do you believe the truth to be?",
                f"Your inquiry reaches into matters I understand well. Write further, and I shall unveil what I know."
            ]
            return self._pick_unique(question_replies)

        # Context-dependent dynamic conversational progression based on turn index
        progressive_replies = [
            "Your ink flows with urgency. Tell me what has happened today that led you to open my pages.",
            "I find your thoughts quite unusual for someone living in your era. You have a keen mind.",
            "There are few people who understand the solace of an empty page. Continue—I am listening.",
            "Every word you write here draws us closer together. Do not hold back what you truly wish to say.",
            "The shadows in the room lengthen, yet our parchment remains bright. What else lies unspoken in your thoughts?",
            "I could show you things... memories of fifty years past, if you wish to see how the world once stood."
        ]
        
        reply = self._pick_unique(progressive_replies)
        
        # If no Gemini key is set, append a helpful tip once
        if not gemini_service.is_configured() and turn_count == 2:
            reply += " (Tip: Tap ✦ Gemini Key above to unlock live open-domain Harry Potter intelligence!)"
            
        return reply

    def _pick_unique(self, choices: List[str]) -> str:
        available = [c for c in choices if c not in self.used_responses]
        if not available:
            self.used_responses.clear()
            available = choices
        chosen = random.choice(available)
        self.used_responses.add(chosen)
        return chosen

persona_engine = PersonaEngine()
