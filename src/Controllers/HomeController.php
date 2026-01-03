<?php

namespace App\Controllers;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use DI\Container;
use App\Traits\RenderTrait;

class HomeController
{
    use RenderTrait;

    public function __construct(\DI\Container $container)
    {
        // No dependencies needed
    }

    public function index(Request $request, Response $response): Response
    {
        $content = $this->render('home.php');
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }
} 