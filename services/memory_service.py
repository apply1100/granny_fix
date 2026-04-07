import collections
from typing import Dict, List, Optional

class MemoryService:
    """A simple in-memory service to keep track of recent messages per chat."""
    
    def __init__(self, max_history_size: int = 15):
        # Dictionary of chat_id -> list of (role, content)
        # Using a deque to automatically handle overflow
        self._memories: Dict[int, collections.deque] = {}
        self._max_history_size = max_history_size

    def add_message(self, chat_id: int, role: str, content: str) -> None:
        """Add a message to the history of a specific chat."""
        if chat_id not in self._memories:
            self._memories[chat_id] = collections.deque(maxlen=self._max_history_size)
        
        self._memories[chat_id].append({"role": role, "content": content})

    def get_history(self, chat_id: int) -> List[Dict[str, str]]:
        """Retrieve the message history for a specific chat."""
        if chat_id not in self._memories:
            return []
        
        return list(self._memories[chat_id])

    def clear_history(self, chat_id: int) -> None:
        """Clears the history for a specific chat."""
        if chat_id in self._memories:
            self._memories[chat_id].clear()

# Global instance
memory_service = MemoryService()
