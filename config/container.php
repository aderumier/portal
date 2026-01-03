<?php

use DI\Container;
use DI\ContainerBuilder;
use App\Controllers\HomeController;
use App\Controllers\CatalogController;
use App\Controllers\AuthController;
use App\Controllers\DownloadController;
use App\Services\GameService;
use App\Services\DownloadService;
use App\Services\DiscordService;
use PDO;

return function (ContainerBuilder $containerBuilder) {
    $containerBuilder->addDefinitions([
        // Controllers
        HomeController::class => function (\DI\Container $c) {
            return new HomeController($c);
        },
        CatalogController::class => function (\DI\Container $c) {
            return new CatalogController($c);
        },
        AuthController::class => function (\DI\Container $c) {
            return new AuthController($c);
        },
        DownloadController::class => function (\DI\Container $c) {
            return new DownloadController($c);
        },

        // Services
        GameService::class => function (\DI\Container $c) {
            return new GameService($_ENV['GAMES_PATH']);
        },
        DownloadService::class => function (\DI\Container $c) {
            return new DownloadService($c);
        },
        DiscordService::class => function (\DI\Container $c) {
            return new DiscordService($c);
        },

        // Database
        PDO::class => function (\DI\Container $c) {
            $dbPath = __DIR__ . '/../data/database.sqlite';
            $dsn = 'sqlite:' . $dbPath;
            
            // Create directory if it doesn't exist
            $dbDir = dirname($dbPath);
            if (!file_exists($dbDir)) {
                mkdir($dbDir, 0777, true);
            }
            
            $pdo = new PDO($dsn);
            $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
            $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
            return $pdo;
        },
    ]);
};