<?php

namespace App\Controllers;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use App\Traits\RenderTrait;
use App\Services\ApiTokenService;
use DI\Container;

class UserController
{
    use RenderTrait;
    
    private $container;
    private $apiTokenService;
    
    public function __construct(Container $container)
    {
        $this->container = $container;
        $this->apiTokenService = $container->get(ApiTokenService::class);
    }
    
    /**
     * Display the user's account page
     */
    public function account(Request $request, Response $response): Response
    {
        // Get current tokens for the user
        $userId = $_SESSION['user']['id'] ?? null;
        
        if (!$userId) {
            return $response->withHeader('Location', '/login')->withStatus(302);
        }
        
        $tokens = $this->apiTokenService->getUserTokens($userId);
        
        // Get the first non-revoked token and store it in the session
        foreach ($tokens as $token) {
            if (!$token['revoked']) {
                $_SESSION['api_token'] = $token['token'];
                break;
            }
        }
        
        $data = [
            'user' => $_SESSION['user'],
            'tokens' => $tokens
        ];
        
        $content = $this->render('account.php', $data);
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }
    
    /**
     * Generate a new API token for the user
     */
    public function generateToken(Request $request, Response $response): Response
    {
        $userId = $_SESSION['user']['id'] ?? null;
        
        if (!$userId) {
            $responseData = ['error' => 'Not authenticated'];
            $response->getBody()->write(json_encode($responseData));
            return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
        }
        
        $data = $request->getParsedBody();
        $name = $data['name'] ?? 'API Token';
        
        try {
            $token = $this->apiTokenService->generateToken($userId, $name);
            
            // Store the token in the session
            $_SESSION['api_token'] = $token;
            
            $responseData = ['token' => $token];
            $response->getBody()->write(json_encode($responseData));
            return $response->withHeader('Content-Type', 'application/json');
        } catch (\Exception $e) {
            $responseData = ['error' => $e->getMessage()];
            $response->getBody()->write(json_encode($responseData));
            return $response->withStatus(500)->withHeader('Content-Type', 'application/json');
        }
    }
    
    /**
     * Revoke an API token
     */
    public function revokeToken(Request $request, Response $response, array $args): Response
    {
        $userId = $_SESSION['user']['id'] ?? null;
        $tokenId = $args['id'] ?? null;
        
        if (!$userId) {
            $responseData = ['error' => 'Not authenticated'];
            $response->getBody()->write(json_encode($responseData));
            return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
        }
        
        if (!$tokenId) {
            $responseData = ['error' => 'Token ID required'];
            $response->getBody()->write(json_encode($responseData));
            return $response->withStatus(400)->withHeader('Content-Type', 'application/json');
        }
        
        try {
            // Get the token before revoking it to check if it's the current session token
            $token = $this->apiTokenService->getTokenById($userId, $tokenId);
            
            $this->apiTokenService->revokeToken($userId, $tokenId);
            
            // If this was the current session token, clear it
            if ($token && isset($_SESSION['api_token']) && $_SESSION['api_token'] === $token['token']) {
                unset($_SESSION['api_token']);
            }
            
            $responseData = ['success' => true];
            $response->getBody()->write(json_encode($responseData));
            return $response->withHeader('Content-Type', 'application/json');
        } catch (\Exception $e) {
            $responseData = ['error' => $e->getMessage()];
            $response->getBody()->write(json_encode($responseData));
            return $response->withStatus(500)->withHeader('Content-Type', 'application/json');
        }
    }
} 