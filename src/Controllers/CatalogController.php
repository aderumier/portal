<?php

namespace App\Controllers;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use App\Services\GameService;
use DI\Container;
use App\Traits\RenderTrait;

class CatalogController
{
    use RenderTrait;
    
    private $gameService;

    public function __construct(\DI\Container $container)
    {
        $this->gameService = $container->get(GameService::class);
    }

    public function index(Request $request, Response $response): Response
    {
        $content = $this->render('home.php');
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }

    public function systems(Request $request, Response $response): Response
    {
        $systems = $this->gameService->getSystems();
        $content = $this->render('systems.php', ['systems' => $systems]);
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }

    public function system(Request $request, Response $response, array $args): Response
    {
        $systemId = $args['id'];
        $system = $this->gameService->getSystem($systemId);
        
        if (!$system) {
            return $response->withStatus(404)->withHeader('Location', '/systems');
        }
        
        // Get search query from request using getQueryParams()
        $queryParams = $request->getQueryParams();
        $searchQuery = $queryParams['search'] ?? '';
        
        // Pass search query to template
        $content = $this->render('system.php', [
            'system' => $system,
            'searchQuery' => $searchQuery
        ]);
        
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }

    public function getSystems(Request $request, Response $response): Response
    {
        $systems = $this->gameService->getSystems();
        $response->getBody()->write(json_encode(['systems' => $systems]));
        return $response->withHeader('Content-Type', 'application/json');
    }

    public function getGames(Request $request, Response $response, array $args): Response
    {
        $system = $args['system'];
        $queryParams = $request->getQueryParams();
        $page = $queryParams['page'] ?? 1;
        $limit = $queryParams['limit'] ?? 12;
        $search = $queryParams['search'] ?? '';

        $games = $this->gameService->getGamesBySystem($system, $page, $limit, $search);
        $hasMore = $this->gameService->hasMoreGames($system, $page, $limit);

        $response->getBody()->write(json_encode([
            'games' => $games,
            'hasMore' => $hasMore
        ]));
        return $response->withHeader('Content-Type', 'application/json');
    }

    public function searchGames(Request $request, Response $response): Response
    {
        $query = $request->getQueryParams()['q'] ?? '';
        $page = $request->getQueryParams()['page'] ?? 1;
        $limit = $request->getQueryParams()['limit'] ?? 12;

        $games = $this->gameService->searchGames($query, $page, $limit);
        $hasMore = $this->gameService->hasMoreSearchResults($query, $page, $limit);

        $response->getBody()->write(json_encode([
            'results' => $games,
            'hasMore' => $hasMore
        ]));
        return $response->withHeader('Content-Type', 'application/json');
    }

    public function search(Request $request, Response $response): Response
    {
        $query = $request->getQueryParams()['q'] ?? '';
        $content = $this->render('search.php', ['query' => $query]);
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }
} 