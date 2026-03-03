"""
Session state management.
Tracks session lifecycle and state in memory.
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import os


@dataclass
class SessionState:
    """State for a single agent session."""

    session_id: str
    created_at: str
    project: Optional[str] = None
    sequence: Optional[str] = None
    shot: Optional[str] = None
    project_path: Optional[str] = None
    sequence_path: Optional[str] = None
    shot_path: Optional[str] = None
    hip_path: Optional[str] = None
    hip_loaded: bool = False
    image_dir: Optional[Path] = None
    
    # Houdini module (lazy loaded)
    hou: Optional[object] = field(default=None, repr=False)
    
    # Environment variables for this session
    env_vars: dict = field(default_factory=dict)


class SessionManager:
    """Manage session lifecycle and state."""
    
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
    
    def create(
        self,
        project: Optional[str] = None,
        sequence: Optional[str] = None,
        shot: Optional[str] = None,
    ) -> SessionState:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        image_dir = Path(f"/tmp/{session_id}/images")
        image_dir.mkdir(parents=True, exist_ok=True)
        
        session = SessionState(
            session_id=session_id,
            created_at=str(uuid.uuid4()),
            project=project,
            sequence=sequence,
            shot=shot,
            image_dir=image_dir,
        )
        
        self._sessions[session_id] = session
        return session
    
    def get(self, session_id: str) -> Optional[SessionState]:
        """Get session by ID."""
        return self._sessions.get(session_id)
    
    def exists(self, session_id: str) -> bool:
        """Check if session exists."""
        return session_id in self._sessions
    
    def destroy(self, session_id: str) -> bool:
        """Destroy session and cleanup."""
        if session_id not in self._sessions:
            return False
        
        session = self._sessions.pop(session_id)
        
        # Cleanup image directory
        if session.image_dir and session.image_dir.exists():
            import shutil
            try:
                shutil.rmtree(session.image_dir, ignore_errors=True)
            except Exception:
                pass
        
        return True
    
    def list_sessions(self) -> list[str]:
        """List all active session IDs."""
        return list(self._sessions.keys())


# Global session manager singleton
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create global session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
