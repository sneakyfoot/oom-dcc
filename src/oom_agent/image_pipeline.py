"""
Image pipeline for storing and retrieving images.
Handles screenshot storage and retrieval.
"""

import base64
from pathlib import Path
from typing import Optional
from datetime import datetime


class ImagePipeline:
    """Manage image storage and retrieval for agent sessions."""
    
    def __init__(self, session_dir: str):
        """Initialize with session directory."""
        self.session_dir = Path(session_dir)
        self.images_dir = self.session_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
    
    def store_image(
        self, image_bytes: bytes, viewport: str = "persp"
    ) -> str:
        """
        Store image to session directory.
        
        Args:
            image_bytes: PNG or JPEG image bytes
            viewport: Viewport name for filename (default: "persp")
        
        Returns:
            Relative path: images/viewport_timestamp.png
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{viewport}_{timestamp}.png"
        image_path = self.images_dir / filename
        
        image_path.write_bytes(image_bytes)
        
        return f"images/{filename}"
    
    def get_image(self, image_path: str) -> Optional[bytes]:
        """
        Retrieve image from session directory.
        
        Args:
            image_path: Relative path like "images/view_20260302_123456.png"
        
        Returns:
            Image bytes or None if not found
        """
        full_path = self.images_dir / image_path
        
        if not full_path.exists():
            return None
        
        return full_path.read_bytes()
    
    def get_image_base64(self, image_path: str) -> Optional[str]:
        """
        Get image as base64 string.
        
        Args:
            image_path: Relative path
        
        Returns:
            Base64 encoded string or None
        """
        image_bytes = self.get_image(image_path)
        if image_bytes is None:
            return None
        return base64.b64encode(image_bytes).decode("utf-8")
    
    def list_images(self) -> list[str]:
        """List all images in session."""
        if not self.images_dir.exists():
            return []
        
        return [f.name for f in self.images_dir.iterdir() if f.is_file()]
    
    def cleanup(self) -> None:
        """Remove all images in session."""
        import shutil
        
        if self.images_dir.exists():
            shutil.rmtree(self.images_dir)
