<?php

namespace App\Middleware;

use Psr\Http\Message\ServerRequestInterface as Request;
use Psr\Http\Server\RequestHandlerInterface as RequestHandler;
use Slim\Psr7\Response;

class AuthMiddleware
{
    public function __invoke(Request $request, RequestHandler $handler): Response
    {
        $path = $request->getUri()->getPath();
        error_log("AuthMiddleware checking path: " . $path);
        
        // Check if user is authenticated via API token
        $authMethod = $request->getAttribute('auth_method');
        if ($authMethod === 'api_token') {
            $userId = $request->getAttribute('user_id');
            if (!$userId) {
                error_log("API token user not authenticated");
                $response = new Response();
                $response->getBody()->write(json_encode(['error' => 'Authentication required']));
                return $response
                    ->withStatus(401)
                    ->withHeader('Content-Type', 'application/json');
            }
            error_log("API token user is authenticated, proceeding with request");
            return $handler->handle($request);
        }
        
        if (!isset($_SESSION['user'])) {
            error_log("No user session found");
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
        
        error_log("User authenticated, proceeding with request");
        return $handler->handle($request);
    }
} 