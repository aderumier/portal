<?php

namespace App\Services;

use DI\Container;
use PDO;

class DownloadService
{
    private $db;
    private $gameService;

    public function __construct(\DI\Container $container)
    {
        $this->db = $container->get(PDO::class);
        $this->gameService = $container->get(GameService::class);
        $this->initializeDatabase();
    }

    private function initializeDatabase(): void
    {
        $this->db->exec("
            CREATE TABLE IF NOT EXISTS download_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                game_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, game_id)
            )
        ");

        // Create games table if it doesn't exist
        $this->db->exec("
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                image TEXT,
                system TEXT NOT NULL
            )
        ");

        // Create systems table if it doesn't exist
        $this->db->exec("
            CREATE TABLE IF NOT EXISTS systems (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ");
    }

    public function addToQueue(string $userId, string $gameId): bool
    {
        try {
            error_log("Adding to queue - Game ID: " . $gameId . ", User ID: " . $userId);
            
            // Clean up the game path by removing ./ prefix
            $gameId = ltrim($gameId, './');
            error_log("Cleaned game ID: " . $gameId);
            
            $parts = explode('/', $gameId);
            if (count($parts) < 2) {
                error_log("Game ID missing system ID, cannot add to queue: " . $gameId);
                return false;
            }
            
            $systemId = $parts[0];
            error_log("System ID extracted: " . $systemId);
            
            // Get game details to verify it exists
            $game = $this->gameService->getGameById($gameId);
            if (!$game) {
                error_log("Game not found: " . $gameId);
                return false;
            }
            
            error_log("Game found, adding to queue: " . $game['name']);

            $stmt = $this->db->prepare("
                INSERT OR IGNORE INTO download_queue (user_id, game_id)
                VALUES (:user_id, :game_id)
            ");

            $result = $stmt->execute([
                ':user_id' => $userId,
                ':game_id' => $gameId
            ]);

            if (!$result) {
                error_log("Failed to insert into download queue: " . json_encode($stmt->errorInfo()));
            }

            return $result;
        } catch (\PDOException $e) {
            error_log("Error adding to download queue: " . $e->getMessage());
            return false;
        } catch (\Exception $e) {
            error_log("Unexpected error adding to download queue: " . $e->getMessage());
            return false;
        }
    }

    public function getQueue(string $userId): array
    {
        try {
            $stmt = $this->db->prepare("
                SELECT q.*
                FROM download_queue q
                WHERE q.user_id = :user_id
                ORDER BY q.created_at DESC
            ");

            $stmt->execute([':user_id' => $userId]);
            $queueItems = $stmt->fetchAll(PDO::FETCH_ASSOC);
            
            // Enrich queue items with game information
            foreach ($queueItems as &$item) {
                $game = $this->gameService->getGameById($item['game_id']);
                if ($game) {
                    $item['game_name'] = $game['name'];
                    $item['image'] = ltrim($game['image'], '/');
                    $item['system_name'] = $this->gameService->getSystemName($game['system']);
                }
            }
            
            return $queueItems;
        } catch (\PDOException $e) {
            error_log("Error getting download queue: " . $e->getMessage());
            return [];
        }
    }

    public function removeFromQueue(string $userId, string $gameId): bool
    {
        try {
            error_log("Removing from queue - Game ID: " . $gameId . ", User ID: " . $userId);
            
            // Clean up the game ID
            $gameId = ltrim($gameId, './');
            error_log("Cleaned game ID: " . $gameId);
            
            $stmt = $this->db->prepare('DELETE FROM download_queue WHERE user_id = ? AND game_id = ?');
            $stmt->execute([$userId, $gameId]);
            
            // Return true if at least one row was affected (game was found and removed)
            $rowCount = $stmt->rowCount();
            error_log("Rows affected: " . $rowCount);
            
            return $rowCount > 0;
        } catch (\PDOException $e) {
            error_log("Database error removing game from queue: " . $e->getMessage());
            throw new \Exception('Failed to remove game from queue: ' . $e->getMessage());
        }
    }

    public function clearQueue(string $userId): bool
    {
        try {
            $stmt = $this->db->prepare('DELETE FROM download_queue WHERE user_id = ?');
            $stmt->execute([$userId]);
            return true;
        } catch (\PDOException $e) {
            error_log("Database error clearing queue: " . $e->getMessage());
            throw new \Exception('Failed to clear queue');
        }
    }

    public function enrichQueueItems(array $queueItems): array
    {
        foreach ($queueItems as &$item) {
            $game = $this->gameService->getGameById($item['game_id']);
            if ($game) {
                $item['game_name'] = $game['name'];
                $item['image'] = ltrim($game['image'], '/');
                $item['system_name'] = $this->gameService->getSystemName($game['system']);
            }
        }
        
        return $queueItems;
    }
} 