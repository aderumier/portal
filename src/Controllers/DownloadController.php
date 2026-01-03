<?php

namespace App\Controllers;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use App\Services\DownloadService;
use DI\Container;
use App\Traits\RenderTrait;
use PDO;

class DownloadController
{
    use RenderTrait;
    
    private $downloadService;
    private $db;

    public function __construct(\DI\Container $container)
    {
        $this->downloadService = $container->get(DownloadService::class);
        $this->db = $container->get(PDO::class);
    }

    public function addToQueue(Request $request, Response $response): Response
    {
        try {
            // Get the authenticated user ID from the request attributes
            $userId = $request->getAttribute('user_id');
            $authMethod = $request->getAttribute('auth_method');
            $isCreator = $request->getAttribute('is_creator', false);
            
            if (!$userId) {
                $response->getBody()->write(json_encode(['error' => 'Not authenticated']));
                return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
            }

            // Check if user has creator role (for web interface) or is using API token (for download service)
            if ($authMethod !== 'api_token' && !$isCreator) {
                $response->getBody()->write(json_encode(['error' => 'Creator role required']));
                return $response->withStatus(403)->withHeader('Content-Type', 'application/json');
            }

            $data = $request->getParsedBody();
            $gameId = $data['game_id'] ?? null;
            
            if (!$gameId) {
                $response->getBody()->write(json_encode(['error' => 'Game ID is required']));
                return $response->withStatus(400)->withHeader('Content-Type', 'application/json');
            }
            
            // Clean up the game path by removing ./ prefix
            $gameId = ltrim($gameId, './');
            
            // Check if the game is already in the queue
            $stmt = $this->db->prepare(
                "SELECT id FROM download_queue 
                 WHERE game_id = ? AND user_id = ?"
            );
            
            $stmt->execute([$gameId, $userId]);
            if ($stmt->fetch()) {
                $response->getBody()->write(json_encode(['error' => 'Game already in queue']));
                return $response->withStatus(400)->withHeader('Content-Type', 'application/json');
            }
            
            // Add to queue
            $stmt = $this->db->prepare(
                "INSERT INTO download_queue (game_id, user_id, created_at) 
                 VALUES (?, ?, datetime('now'))"
            );
            
            $stmt->execute([$gameId, $userId]);
            
            $response->getBody()->write(json_encode(['success' => true]));
            return $response->withHeader('Content-Type', 'application/json');
        } catch (\Exception $e) {
            error_log("Error adding to queue: " . $e->getMessage());
            $response->getBody()->write(json_encode(['error' => 'Failed to add to queue']));
            return $response->withStatus(500)->withHeader('Content-Type', 'application/json');
        }
    }

    public function getQueue(Request $request, Response $response): Response
    {
        try {
            // Get the authenticated user ID from the request attributes
            $userId = $request->getAttribute('user_id');
            $authMethod = $request->getAttribute('auth_method');
            $isCreator = $request->getAttribute('is_creator', false);
            
            if (!$userId) {
                $response->getBody()->write(json_encode(['error' => 'Not authenticated']));
                return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
            }

            // Check if user has creator role (for web interface) or is using API token (for download service)
            if ($authMethod !== 'api_token' && !$isCreator) {
                $response->getBody()->write(json_encode(['error' => 'Creator role required']));
                return $response->withStatus(403)->withHeader('Content-Type', 'application/json');
            }

            // Get the queue from the database
            $stmt = $this->db->prepare(
                "SELECT q.*, g.name as game_name 
                 FROM download_queue q 
                 JOIN games g ON q.game_id = g.id 
                 WHERE q.user_id = ? 
                 ORDER BY q.created_at ASC"
            );
            
            $stmt->execute([$userId]);
            $queue = $stmt->fetchAll(PDO::FETCH_ASSOC);
            
            $response->getBody()->write(json_encode($queue));
            return $response->withHeader('Content-Type', 'application/json');
        } catch (\Exception $e) {
            error_log("Error fetching queue: " . $e->getMessage());
            $response->getBody()->write(json_encode(['error' => 'Failed to fetch queue']));
            return $response->withStatus(500)->withHeader('Content-Type', 'application/json');
        }
    }

    public function removeFromQueue(Request $request, Response $response, array $args): Response
    {
        try {
            // Get the authenticated user ID from the request attributes
            $userId = $request->getAttribute('user_id');
            
            if (!$userId) {
                $response->getBody()->write(json_encode(['error' => 'Not authenticated']));
                return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
            }

            $gameId = $args['gameId'] ?? null;
            if (!$gameId) {
                $response->getBody()->write(json_encode(['error' => 'Game ID is required']));
                return $response->withStatus(400)->withHeader('Content-Type', 'application/json');
            }

            // Double URL decode the game ID (needed for IDs with spaces and special characters)
            $gameId = urldecode(urldecode($gameId));

            // Remove from queue
            $stmt = $this->db->prepare(
                "DELETE FROM download_queue 
                 WHERE game_id = ? AND user_id = ?"
            );
            
            $stmt->execute([$gameId, $userId]);
            
            if ($stmt->rowCount() === 0) {
                $response->getBody()->write(json_encode(['error' => 'Game not found in queue']));
                return $response->withStatus(404)->withHeader('Content-Type', 'application/json');
            }
            
            $response->getBody()->write(json_encode(['success' => true]));
            return $response->withHeader('Content-Type', 'application/json');
        } catch (\Exception $e) {
            error_log("Error removing game from queue: " . $e->getMessage());
            $response->getBody()->write(json_encode(['error' => 'Failed to remove game from queue']));
            return $response->withStatus(500)->withHeader('Content-Type', 'application/json');
        }
    }

    public function clearQueue(Request $request, Response $response): Response
    {
        try {
            // Get the authenticated user ID from the request attributes
            $userId = $request->getAttribute('user_id');
            
            if (!$userId) {
                $response->getBody()->write(json_encode(['error' => 'Not authenticated']));
                return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
            }

            // Clear the queue for this user
            $stmt = $this->db->prepare(
                "DELETE FROM download_queue 
                 WHERE user_id = ?"
            );
            
            $stmt->execute([$userId]);
            
            $response->getBody()->write(json_encode(['success' => true]));
            return $response->withHeader('Content-Type', 'application/json');
        } catch (\Exception $e) {
            error_log("Error clearing queue: " . $e->getMessage());
            $response->getBody()->write(json_encode(['error' => 'Failed to clear queue']));
            return $response->withStatus(500)->withHeader('Content-Type', 'application/json');
        }
    }

    public function downloads(Request $request, Response $response): Response
    {
        // Get the authenticated user ID from the request attributes
        $userId = $request->getAttribute('user_id');
        $authMethod = $request->getAttribute('auth_method');
        $isCreator = $request->getAttribute('is_creator', false);
        
        if (!$userId) {
            return $response->withHeader('Location', '/login')->withStatus(302);
        }

        // Check if user has creator role (for web interface)
        // API tokens don't typically access this HTML page, but we include the check for consistency
        if ($authMethod !== 'api_token' && !$isCreator) {
            error_log("User $userId tried to access downloads page without creator role");
            return $response->withHeader('Location', '/unauthorized')->withStatus(302);
        }

        // Get the queue from the database
        $stmt = $this->db->prepare(
            "SELECT q.* 
             FROM download_queue q
             WHERE q.user_id = ? 
             ORDER BY q.created_at ASC"
        );
        
        $stmt->execute([$userId]);
        $queue = $stmt->fetchAll(PDO::FETCH_ASSOC);
        
        // Enrich queue items with game information
        $queue = $this->downloadService->enrichQueueItems($queue);
        
        $content = $this->render('downloads.php', ['queue' => $queue]);
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }

    public function markCompleted(Request $request, Response $response): Response
    {
        try {
            // Get the authenticated user ID from the request attributes
            $userId = $request->getAttribute('user_id');
            
            if (!$userId) {
                $response->getBody()->write(json_encode(['error' => 'Not authenticated']));
                return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
            }

            $data = $request->getParsedBody();
            $gameId = $data['game_id'] ?? null;
            
            if (!$gameId) {
                $response->getBody()->write(json_encode(['error' => 'Game ID is required']));
                return $response->withStatus(400)->withHeader('Content-Type', 'application/json');
            }
            
            // Mark the game as completed in the queue
            $stmt = $this->db->prepare(
                "DELETE FROM download_queue 
                 WHERE game_id = ? AND user_id = ?"
            );
            
            $stmt->execute([$gameId, $userId]);
            
            if ($stmt->rowCount() === 0) {
                $response->getBody()->write(json_encode(['error' => 'Game not found in queue']));
                return $response->withStatus(404)->withHeader('Content-Type', 'application/json');
            }
            
            $response->getBody()->write(json_encode(['success' => true]));
            return $response->withHeader('Content-Type', 'application/json');
        } catch (\Exception $e) {
            error_log("Error marking game as completed: " . $e->getMessage());
            $response->getBody()->write(json_encode(['error' => 'Failed to mark game as completed']));
            return $response->withStatus(500)->withHeader('Content-Type', 'application/json');
        }
    }
} 