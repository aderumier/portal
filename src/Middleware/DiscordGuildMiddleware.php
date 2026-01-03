<?php

namespace App\Middleware;

use Psr\Http\Message\ServerRequestInterface as Request;
use Psr\Http\Server\RequestHandlerInterface as RequestHandler;
use Slim\Psr7\Response;
use App\Services\DiscordService;

class DiscordGuildMiddleware
{
    private $discordService;
    private $requiredGuildName = "Team Pixel Nostalgia";

    public function __construct(DiscordService $discordService)
    {
        $this->discordService = $discordService;
    }

    public function __invoke(Request $request, RequestHandler $handler): Response
    {
        $path = $request->getUri()->getPath();
        error_log("DiscordGuildMiddleware checking path: " . $path);
        
        // Check if user is authenticated via API token
        $authMethod = $request->getAttribute('auth_method');
        if ($authMethod === 'api_token') {
            $isGuildMember = $request->getAttribute('is_guild_member', false);
            if (!$isGuildMember) {
                error_log("API token user is not a guild member");
                $response = new Response();
                $response->getBody()->write(json_encode([
                    'error' => 'Guild membership required',
                    'guild' => $this->requiredGuildName
                ]));
                return $response
                    ->withStatus(403)
                    ->withHeader('Content-Type', 'application/json');
            }
            error_log("API token user is a guild member, proceeding with request");
            return $handler->handle($request);
        }
        
        // For web interface users, check session
        if (!isset($_SESSION['user']) || empty($_SESSION['user']['id'])) {
            error_log("User not logged in, redirecting to login");
            $response = new Response();
            
            // Check if this is an API request
            if (strpos($path, '/api/') === 0) {
                error_log("API request without authentication");
                $response->getBody()->write(json_encode(['error' => 'Authentication required']));
                return $response
                    ->withStatus(401)
                    ->withHeader('Content-Type', 'application/json');
            } else {
                error_log("Redirecting to login page");
                return $response->withHeader('Location', '/login')->withStatus(302);
            }
        }
        
        // Debugging session data
        error_log("Session user data: " . json_encode($_SESSION['user']));

        // For web interface users, check if they have the creator role
        if (strpos($path, '/api/') === 0) {
            $isCreator = $request->getAttribute('is_creator', false);
            if (!$isCreator) {
                error_log("User does not have creator role");
                $response = new Response();
                $response->getBody()->write(json_encode([
                    'error' => 'Creator role required'
                ]));
                return $response
                    ->withStatus(403)
                    ->withHeader('Content-Type', 'application/json');
            }
        }

        error_log("User is authorized, proceeding with request");
        return $handler->handle($request);
    }
} 