<?php

namespace App\Services;

use PDO;

class ApiTokenService
{
    private $db;
    
    public function __construct(PDO $db)
    {
        $this->db = $db;
        $this->initializeTable();
    }
    
    /**
     * Initialize the API tokens table if it doesn't exist
     */
    private function initializeTable(): void
    {
        $sql = "CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            token TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT NULL,
            revoked BOOLEAN DEFAULT 0
        )";
        
        $this->db->exec($sql);
    }
    
    /**
     * Generate a new API token for a user
     */
    public function generateToken(string $userId, string $name): string
    {
        // Generate a secure random token
        $token = bin2hex(random_bytes(32));
        
        // Insert the token into the database
        $stmt = $this->db->prepare(
            "INSERT INTO api_tokens (user_id, token, name, created_at) VALUES (?, ?, ?, datetime('now'))"
        );
        
        $stmt->execute([$userId, $token, $name]);
        
        return $token;
    }
    
    /**
     * Validate an API token and return the user ID if valid
     */
    public function validateToken(string $token): ?string
    {
        // Look up the token in the database
        $stmt = $this->db->prepare(
            "SELECT user_id FROM api_tokens 
             WHERE token = ? AND revoked = 0"
        );
        
        $stmt->execute([$token]);
        $result = $stmt->fetch(PDO::FETCH_ASSOC);
        
        if (!$result) {
            return null;
        }
        
        return $result['user_id'];
    }
    
    /**
     * Get a token by its ID
     */
    public function getTokenById(string $userId, int $tokenId): ?array
    {
        $stmt = $this->db->prepare(
            "SELECT id, token, name, created_at, last_used_at, revoked 
             FROM api_tokens 
             WHERE id = ? AND user_id = ?"
        );
        
        $stmt->execute([$tokenId, $userId]);
        return $stmt->fetch(PDO::FETCH_ASSOC);
    }
    
    /**
     * Get all tokens for a user
     */
    public function getUserTokens(string $userId): array
    {
        $stmt = $this->db->prepare(
            "SELECT id, name, token, substr(token, 1, 8) || '...' as token_preview, 
             created_at, last_used_at, revoked 
             FROM api_tokens 
             WHERE user_id = ? 
             ORDER BY created_at DESC"
        );
        
        $stmt->execute([$userId]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }
    
    /**
     * Revoke a token
     */
    public function revokeToken(string $userId, int $tokenId): void
    {
        $stmt = $this->db->prepare(
            "UPDATE api_tokens SET revoked = 1 
             WHERE id = ? AND user_id = ?"
        );
        
        $stmt->execute([$tokenId, $userId]);
        
        if ($stmt->rowCount() === 0) {
            throw new \Exception("Token not found or doesn't belong to the user");
        }
    }
    
    /**
     * Extract token from Authorization header
     */
    public function extractTokenFromHeader(string $authHeader): ?string
    {
        if (preg_match('/Bearer\s+(\S+)/', $authHeader, $matches)) {
            return $matches[1];
        }
        
        return null;
    }
} 