"""Download queue service."""
import logging
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.database import DownloadQueue
from app.services.game import GameService

logger = logging.getLogger(__name__)

class DownloadService:
    """Service for managing download queue."""
    
    def __init__(self, db: Session, game_service: GameService):
        self.db = db
        self.game_service = game_service
    
    def add_to_queue(self, user_id: str, game_id: str) -> bool:
        """Add a game to the download queue."""
        try:
            logger.info(f"Adding to queue - Game ID: {game_id}, User ID: {user_id}")
            
            # Clean up the game path by removing ./ prefix
            game_id = game_id.lstrip('./')
            logger.info(f"Cleaned game ID: {game_id}")
            
            # Check if game exists
            game = self.game_service.get_game_by_id(game_id)
            if not game:
                logger.warning(f"Game not found: {game_id}")
                return False
            
            logger.info(f"Game found, adding to queue: {game['name']}")
            
            # Check if already in queue
            existing = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.game_id == game_id
                )
            ).first()
            
            if existing:
                logger.warning(f"Game already in queue: {game_id}")
                return False
            
            # Add to queue
            queue_item = DownloadQueue(
                user_id=user_id,
                game_id=game_id,
                status='pending'
            )
            
            self.db.add(queue_item)
            self.db.commit()
            
            logger.info(f"Successfully added game to queue: {game_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding to download queue: {e}")
            self.db.rollback()
            return False
    
    def get_queue(self, user_id: str) -> List[Dict]:
        """Get download queue for a user."""
        try:
            queue_items = self.db.query(DownloadQueue).filter(
                DownloadQueue.user_id == user_id
            ).order_by(DownloadQueue.created_at.desc()).all()
            
            # Enrich queue items with game information
            enriched_items = []
            for item in queue_items:
                game = self.game_service.get_game_by_id(item.game_id)
                if game:
                    enriched_item = {
                        'id': item.id,
                        'user_id': item.user_id,
                        'game_id': item.game_id,
                        'status': item.status,
                        'created_at': item.created_at.isoformat() if item.created_at else None,
                        'game_name': game['name'],
                        'image': game.get('image', ''),
                        'system_name': self.game_service.get_system_name(game.get('system', ''))
                    }
                    enriched_items.append(enriched_item)
            
            return enriched_items
        except Exception as e:
            logger.error(f"Error getting download queue: {e}")
            return []
    
    def remove_from_queue(self, user_id: str, game_id: str) -> bool:
        """Remove a game from the download queue."""
        try:
            logger.info(f"Removing from queue - Game ID: {game_id}, User ID: {user_id}")
            
            # Clean up the game ID
            game_id = game_id.lstrip('./')
            logger.info(f"Cleaned game ID: {game_id}")
            
            queue_item = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.game_id == game_id
                )
            ).first()
            
            if not queue_item:
                logger.warning(f"Game not found in queue: {game_id}")
                return False
            
            self.db.delete(queue_item)
            self.db.commit()
            
            logger.info(f"Successfully removed game from queue: {game_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing game from queue: {e}")
            self.db.rollback()
            return False
    
    def clear_queue(self, user_id: str) -> bool:
        """Clear all games from the download queue for a user."""
        try:
            self.db.query(DownloadQueue).filter(
                DownloadQueue.user_id == user_id
            ).delete()
            self.db.commit()
            
            logger.info(f"Successfully cleared queue for user: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error clearing queue: {e}")
            self.db.rollback()
            return False
    
    def enrich_queue_items(self, queue_items: List[Dict]) -> List[Dict]:
        """Enrich queue items with game metadata."""
        enriched = []
        for item in queue_items:
            game = self.game_service.get_game_by_id(item.get('game_id', ''))
            if game:
                enriched_item = item.copy()
                enriched_item['game_name'] = game['name']
                enriched_item['image'] = game.get('image', '').lstrip('/')
                enriched_item['system_name'] = self.game_service.get_system_name(game.get('system', ''))
                enriched.append(enriched_item)
            else:
                enriched.append(item)
        return enriched

