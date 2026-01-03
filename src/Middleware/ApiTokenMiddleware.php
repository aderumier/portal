<?php

namespace App\Middleware;

use Psr\Http\Message\ServerRequestInterface as Request;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface as RequestHandler;
use App\Services\ApiTokenService;
use App\Services\DiscordService;

class ApiTokenMiddleware implements MiddlewareInterface
{
    private $apiTokenService;
    private $discordService;
    
    public function __construct(ApiTokenService $apiTokenService, DiscordService $discordService)
    {
        $this->apiTokenService = $apiTokenService;
        $this->discordService = $discordService;
    }
    
    public function process(Request $request, RequestHandler $handler): Response
    {
        // Check for Authorization header
        $authHeader = $request->getHeaderLine('Authorization');
        
        if (empty($authHeader)) {
            // No token provided, set attributes from session for web interface users
            if (isset($_SESSION['user'])) {
                $request = $request->withAttribute('user_id', $_SESSION['user']['id']);
                $request = $request->withAttribute('auth_method', 'session');
                $request = $request->withAttribute('is_creator', $_SESSION['user']['is_creator'] ?? false);
                $request = $request->withAttribute('is_guild_member', $_SESSION['user']['is_guild_member'] ?? false);
                error_log("Setting session attributes - user_id: " . $_SESSION['user']['id'] . ", is_creator: " . ($_SESSION['user']['is_creator'] ?? false));
            }
            return $handler->handle($request);
        }
        
        // Extract token from header
        $token = $this->apiTokenService->extractTokenFromHeader($authHeader);
        
        if (!$token) {
            // Invalid token format
            $response = new \Slim\Psr7\Response();
            return $response
                ->withStatus(401)
                ->withHeader('Content-Type', 'application/json')
                ->withBody(self::writeJson(['error' => 'Invalid token format']));
        }
        
        // Validate token
        $userId = $this->apiTokenService->validateToken($token);
        
        if (!$userId) {
            // Token is invalid or revoked
            $response = new \Slim\Psr7\Response();
            return $response
                ->withStatus(401)
                ->withHeader('Content-Type', 'application/json')
                ->withBody(self::writeJson(['error' => 'Invalid or revoked token']));
        }
        
        // For API token requests, we don't need to check Discord roles
        // Set user info in request attributes for access in controllers
        $request = $request->withAttribute('user_id', $userId);
        $request = $request->withAttribute('auth_method', 'api_token');
        
        // Continue with the modified request
        return $handler->handle($request);
    }
    
    private static function writeJson(array $data): \Psr\Http\Message\StreamInterface
    {
        $json = json_encode($data);
        $stream = fopen('php://temp', 'r+');
        fwrite($stream, $json);
        rewind($stream);
        return new \Slim\Psr7\Stream($stream);
    }
} 