<?php

use App\Services\GameService;
use App\Services\DownloadService;
use App\Services\DiscordService;
use App\Middleware\AuthMiddleware;
use App\Middleware\DiscordGuildMiddleware;
use App\Middleware\CreatorRoleMiddleware;
use Psr\Container\ContainerInterface;
use DI\Container;

return function (Container $container) {
    // Services
    $container->set(GameService::class, function (ContainerInterface $c) {
        $rootDir = dirname(__DIR__);
        $gamesPath = $rootDir . '/games';
        return new GameService($gamesPath);
    });

    $container->set(DownloadService::class, function (ContainerInterface $c) {
        return new DownloadService();
    });

    $container->set(DiscordService::class, function (ContainerInterface $c) {
        return new DiscordService($c);
    });

    // Middleware
    $container->set(AuthMiddleware::class, function (ContainerInterface $c) {
        return new AuthMiddleware();
    });

    $container->set(DiscordGuildMiddleware::class, function (ContainerInterface $c) {
        return new DiscordGuildMiddleware($c->get(DiscordService::class));
    });
    
    $container->set(CreatorRoleMiddleware::class, function (ContainerInterface $c) {
        return new CreatorRoleMiddleware($c->get(DiscordService::class));
    });
}; 