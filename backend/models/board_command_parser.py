"""Constrained detection of an @board invocation in recognized handwriting."""
import re
from typing import Dict


_TRIGGER = re.compile(r"^\s*(?:@\s*b[o0]ard|at\s+board)\b\s*[,.:;\-]?\s*", re.IGNORECASE)


def extract_board_command(text: str) -> Dict[str, object]:
    """Recognize only an invocation at the start of the transcription.

    Accepts OCR's common ``@ board`` and spoken-form ``at board`` variants;
    an unrelated occurrence of the word board is deliberately not a trigger.
    """
    transcription = (text or "").strip()
    match = _TRIGGER.match(transcription)
    if not match:
        return {"command_detected": False, "command_text": None,
                "instruction_missing": False}
    instruction = transcription[match.end():].strip()
    return {"command_detected": True, "command_text": instruction or None,
            "instruction_missing": not bool(instruction)}
