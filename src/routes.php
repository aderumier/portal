<?php

use Slim\App;
use Slim\Routing\RouteCollectorProxy;
use App\Controllers\HomeController;
use App\Controllers\CatalogController;
use App\Controllers\AuthController;
use App\Controllers\DownloadController;
use App\Controllers\UserController;
use App\Middleware\AuthMiddleware;
use App\Middleware\DiscordGuildMiddleware;
use App\Middleware\CreatorRoleMiddleware;
use App\Middleware\ApiTokenMiddleware;
use Psr\Http\Message\RequestInterface as Request;
use Psr\Http\Message\ResponseInterface as Response;
use App\Services\DiscordService;

return function (App $app) {
    // Get the container from the app
    $container = $app->getContainer();
    
    // Public routes
    $app->get('/', [HomeController::class, 'index']);
    $app->get('/login', [AuthController::class, 'login']);
    $app->get('/callback', [AuthController::class, 'callback']);
    $app->get('/auth/discord/callback', [AuthController::class, 'callback']);
    $app->get('/logout', [AuthController::class, 'logout']);
    $app->get('/unauthorized', [AuthController::class, 'unauthorized']);

    // Debug route for Discord role checking - behind auth middleware to avoid abuse
    $app->get('/debug/discord-roles', function (Request $request, Response $response) use ($container) {
        if (!isset($_SESSION['user']) || empty($_SESSION['user']['id'])) {
            $response->getBody()->write(json_encode(['error' => 'Not authenticated']));
            return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
        }
        
        $discordService = $container->get(DiscordService::class);
        $userId = $_SESSION['user']['id'];
        
        // Get debug information
        $debugInfo = $discordService->debugTokenAndRoles($userId);
        
        // Add session info
        $debugInfo['SESSION_DATA'] = [
            'is_guild_member' => $_SESSION['user']['is_guild_member'] ?? false,
            'is_creator' => $_SESSION['user']['is_creator'] ?? false,
            'username' => $_SESSION['user']['username'] ?? 'unknown'
        ];
        
        // Return as JSON
        $response->getBody()->write(json_encode($debugInfo, JSON_PRETTY_PRINT));
        return $response->withHeader('Content-Type', 'application/json');
    });

    // Protected routes (require Discord guild membership)
    $app->group('', function (RouteCollectorProxy $group) {
        // Catalog routes
        $group->get('/systems', [CatalogController::class, 'systems']);
        $group->get('/system/{id}', [CatalogController::class, 'system']);
        $group->get('/search', [CatalogController::class, 'search']);
        $group->get('/api/systems', [CatalogController::class, 'getSystems']);
        $group->get('/api/games/{system}', [CatalogController::class, 'getGames']);
        $group->get('/api/search', [CatalogController::class, 'searchGames']);
        
        // User account routes
        $group->get('/account', [UserController::class, 'account']);
        $group->post('/api/tokens', [UserController::class, 'generateToken']);
        $group->delete('/api/tokens/{id}', [UserController::class, 'revokeToken']);

        // Download routes (accessible via creator role or API token)
        $group->get('/downloads', [DownloadController::class, 'downloads']);
        
        // Download queue API routes
        $group->group('/api/download/queue', function (RouteCollectorProxy $group) {
            $group->get('', [DownloadController::class, 'getQueue']);
            $group->post('', [DownloadController::class, 'addToQueue']);
            $group->delete('/{gameId}', [DownloadController::class, 'removeFromQueue']);
            $group->delete('', [DownloadController::class, 'clearQueue']);
        });
        
        // API for service integration
        $group->post('/api/download/complete', [DownloadController::class, 'markCompleted']);

        // Creator-only routes (require creator role)
        $group->group('', function (RouteCollectorProxy $creatorGroup) {
            // Add creator-only routes here
        })->add(CreatorRoleMiddleware::class);
    })->add(AuthMiddleware::class)->add(DiscordGuildMiddleware::class)->add(ApiTokenMiddleware::class);
}; 