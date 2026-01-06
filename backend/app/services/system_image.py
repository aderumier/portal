"""Service for managing system images."""
import os
import subprocess
from pathlib import Path
from typing import Optional
from PIL import Image
import logging

logger = logging.getLogger(__name__)

class SystemImageService:
    """Service for uploading and converting system images."""
    
    def __init__(self):
        # Path to systems_logos directory
        # In development: frontend/public/systems_logos
        # In production (.deb): frontend/dist/systems_logos (files are served from dist)
        possible_paths = [
            Path('/opt/batocera-games-catalog/frontend/dist/systems_logos'),  # Production (.deb)
            Path(__file__).parent.parent.parent.parent / 'frontend' / 'dist' / 'systems_logos',  # Development build
            Path(__file__).parent.parent.parent.parent / 'frontend' / 'public' / 'systems_logos',  # Development source
            Path('/opt/batocera-games-catalog/frontend/public/systems_logos'),  # Fallback production
            Path(__file__).parent.parent.parent / 'frontend' / 'public' / 'systems_logos',  # Fallback
        ]
        
        self.systems_logos_path = None
        for path in possible_paths:
            if path.exists():
                self.systems_logos_path = path
                logger.info(f"Found systems_logos directory at: {self.systems_logos_path}")
                break
        
        if not self.systems_logos_path:
            # Try to determine if we're in production or development
            # Check if /opt/batocera-games-catalog exists (production)
            production_base = Path('/opt/batocera-games-catalog/frontend')
            if production_base.exists():
                # Production: use dist
                self.systems_logos_path = production_base / 'dist' / 'systems_logos'
            else:
                # Development: use public
                self.systems_logos_path = Path(__file__).parent.parent.parent.parent / 'frontend' / 'public' / 'systems_logos'
            
            self.systems_logos_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created systems_logos directory at: {self.systems_logos_path}")
    
    def convert_to_webp(self, input_path: Path, output_path: Path) -> bool:
        """Convert image to WebP format."""
        try:
            # Try using cwebp first (better quality)
            try:
                result = subprocess.run(
                    ['cwebp', '-q', '90', str(input_path), '-o', str(output_path)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    logger.info(f"Converted {input_path.name} to WebP using cwebp")
                    return True
                else:
                    logger.warning(f"cwebp failed: {result.stderr}")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                logger.info("cwebp not available, using Pillow")
            
            # Fallback to Pillow
            with Image.open(input_path) as img:
                # Convert RGBA to RGB if necessary (WebP doesn't support RGBA well)
                if img.mode == 'RGBA':
                    # Create white background
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[3])  # Use alpha channel as mask
                    img = rgb_img
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                
                img.save(output_path, 'WEBP', quality=90)
                logger.info(f"Converted {input_path.name} to WebP using Pillow")
                return True
                
        except Exception as e:
            logger.error(f"Error converting image to WebP: {e}", exc_info=True)
            return False
    
    def upload_system_image(self, system_id: str, file_content: bytes, file_extension: str) -> bool:
        """Upload and convert system image to WebP format.
        
        In production, writes to both dist (for immediate serving) and public (for persistence across builds).
        
        Args:
            system_id: System ID (e.g., 'nes', 'snes')
            file_content: Image file content as bytes
            file_extension: Original file extension (png, jpg, etc.)
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create temporary file with original extension
            temp_dir = self.systems_logos_path / '.temp'
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / f"{system_id}.{file_extension}"
            
            # Write temporary file
            with open(temp_file, 'wb') as f:
                f.write(file_content)
            
            # Output WebP file
            output_file = self.systems_logos_path / f"{system_id}.webp"
            
            # Convert to WebP
            success = self.convert_to_webp(temp_file, output_file)
            
            # Clean up temporary file
            if temp_file.exists():
                temp_file.unlink()
            
            if success:
                logger.info(f"Successfully uploaded and converted system image: {output_file}")
                
                # In production, also write to public directory so it persists across builds
                # Check if we're in production (/opt/batocera-games-catalog)
                if '/opt/batocera-games-catalog' in str(self.systems_logos_path):
                    public_path = Path('/opt/batocera-games-catalog/frontend/public/systems_logos')
                    public_path.mkdir(parents=True, exist_ok=True)
                    public_output = public_path / f"{system_id}.webp"
                    try:
                        # Copy to public directory
                        import shutil
                        shutil.copy2(output_file, public_output)
                        logger.info(f"Also copied to public directory: {public_output}")
                    except Exception as e:
                        logger.warning(f"Could not copy to public directory: {e}")
                
                return True
            else:
                logger.error(f"Failed to convert system image: {system_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error uploading system image: {e}", exc_info=True)
            return False
    
    def get_system_image_path(self, system_id: str) -> Optional[Path]:
        """Get path to system image if it exists."""
        image_path = self.systems_logos_path / f"{system_id}.webp"
        if image_path.exists():
            return image_path
        return None

