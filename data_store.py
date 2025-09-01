import time
from typing import Dict, Any, List, Optional

# This is a simple in-memory list to store meeting data.
# In a real application, this would be a database (PostgreSQL, SQLite, etc.).
# Each dictionary represents a "meeting" entry. The 'time' field
# can be used to determine the "latest" entry.
# For simplicity, 'time' here will be a float (Unix timestamp).
_meeting_data_store: List[Dict[str, Any]] = [
    {
        "user": "U07FD5Q777E", # Replace with a real user ID from your workspace for testing
        "time": time.time() - 3600 * 24 * 7, # A week ago
        "summary": "Discussed Q2 performance, initial budget for Q3, and new client onboarding process. Michael seemed concerned about the lack of synergy.",
        "todo": "- Follow up on Q3 budget (Dwight)\n- Schedule client kickoff (Pam)",
        "userstories": "- As a client, I want to be onboarded smoothly so I can start using the product quickly.",
    },
    {
        "user": "U07FZF8KVRN", # Another dummy user ID
        "time": time.time(), # Now (latest meeting)
        "summary": "Brainstormed ideas for the new paper recycling initiative. Michael suggested a 'fun run' to raise awareness. Dwight had strong feelings about beet farming.",
        "todo": "- Research local recycling centers (Angela)\n- Draft 'fun run' proposal (Michael)\n- Order more beets (Dwight)",
        "userstories": "- As an employee, I want to easily dispose of paper waste so I can contribute to sustainability.\n- As a manager, I want to track recycling metrics to report on environmental impact."
    },
    {
        "user": "U08TN52A9PS", # Another dummy user ID
        "time": time.time(), # Now (latest meeting)
        "summary": "Brainstormed ideas for the new paper recycling initiative. Michael suggested a 'fun run' to raise awareness. Dwight had strong feelings about beet farming.",
        "todo": "- Research local recycling centers (Angela)\n- Draft 'fun run' proposal (Michael)\n- Order more beets (Dwight)",
        "userstories": "- As an employee, I want to easily dispose of paper waste so I can contribute to sustainability.\n- As a manager, I want to track recycling metrics to report on environmental impact."
    }
]

def get_latest_meeting_data(data_type: str) -> Optional[str]:
    
    if not _meeting_data_store:
        return None

    # Sort by time to get the latest meeting entry
    latest_meeting = max(_meeting_data_store, key=lambda x: x["time"])

    return latest_meeting.get(data_type)