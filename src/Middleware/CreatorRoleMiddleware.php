<?php

namespace App\Middleware;

use Psr\Http\Message\ServerRequestInterface as Request;
use Psr\Http\Server\RequestHandlerInterface as RequestHandler;
use Slim\Psr7\Response;
use App\Services\DiscordService;

class CreatorRoleMiddleware
{
    private $discordService;

    public function __construct(DiscordService $discordService)
    {
        $this->discordService = $discordService;
    }

    public function __invoke(Request $request, RequestHandler $handler): Response
    {
        $path = $request->getUri()->getPath();
        error_log("CreatorRoleMiddleware checking path: " . $path);
        
        // Check if user is authenticated via API token
        $authMethod = $request->getAttribute('auth_method');
        if ($authMethod === 'api_token') {
            error_log("API token request, skipping creator role check");
            return $handler->handle($request);
        }
        
        // Check if session exists and user is a guild member
        if (!isset($_SESSION['user']) || !isset($_SESSION['user']['is_guild_member']) || !$_SESSION['user']['is_guild_member']) {
            error_log("User not logged in or not a guild member");
            return $this->handleUnauthorized($path);
        }
        
        // Check if user has creator role
        if (!isset($_SESSION['user']['is_creator']) || !$_SESSION['user']['is_creator']) {
            error_log("User does not have creator role");
            return $this->handleUnauthorized($path);
        }
        
        error_log("User is a creator, proceeding with request");
        return $handler->handle($request);
    }
    
    private function handleUnauthorized(string $path): Response
    {
        $response = new Response();
        
        // Check if this is an API request
        if (strpos($path, '/api/') === 0) {
            error_log("API request without creator role");
            $response->getBody()->write(json_encode([
                'error' => 'Creator role required',
            ]));
            return $response
                ->withStatus(403)
                ->withHeader('Content-Type', 'application/json');
        } else {
            error_log("Redirecting to unauthorized page");
            return $response->withHeader('Location', '/unauthorized')->withStatus(302);
        }
    }
} 