<?php

namespace App\Services;

use DI\Container;

class GameService
{
    private $gamesPath;
    private $cache = [];

    public function __construct(string $gamesPath = null)
    {
        $this->gamesPath = $gamesPath ?? $_ENV['GAMES_PATH'] ?? __DIR__ . '/../../data/games';
    }

    public function getSystems(): array
    {
        error_log("Getting systems");
        
        if (isset($this->cache['systems'])) {
            return $this->cache['systems'];
        }

        $systems = [];
        if (!is_dir($this->gamesPath)) {
            error_log("Games directory not found at: " . $this->gamesPath);
            return [];
        }

        $dirs = scandir($this->gamesPath);
        foreach ($dirs as $dir) {
            if ($dir === '.' || $dir === '..') {
                continue;
            }

            $path = $this->gamesPath . '/' . $dir;
            if (!is_dir($path) || !is_readable($path)) {
                error_log("Directory not readable: " . $path);
                continue;
            }

            $gamelistPath = $path . '/gamelist.xml';
            if (!file_exists($gamelistPath) || !is_readable($gamelistPath)) {
                error_log("No gamelist.xml found for system: " . $dir);
                continue;
            }

            $gameCount = 0;
            $xml = simplexml_load_file($gamelistPath);
            if ($xml) {
                // Count only non-hidden games
                $allGames = $xml->xpath('//game');
                foreach ($allGames as $game) {
                    // Skip games with hidden attribute set to true
                    if (isset($game->hidden) && ((string)$game->hidden === 'true' || (string)$game->hidden === '1')) {
                        continue;
                    }
                    $gameCount++;
                }
            }

            $system = [
                'id' => $dir,
                'name' => $this->getSystemName($dir),
                'gameCount' => $gameCount
            ];

            $systems[] = $system;
        }

        $this->cache['systems'] = $systems;
        return $systems;
    }

    public function getSystem(string $systemId): ?array
    {
        $systems = $this->getSystems();
        foreach ($systems as $system) {
            if ($system['id'] === $systemId) {
                return $system;
            }
        }
        return null;
    }

    public function getGamesBySystem(string $system, int $page = 1, int $limit = 12, string $search = ''): array
    {
        error_log("Getting games for system: " . $system . ", page: " . $page . ", limit: " . $limit);
        
        $cacheKey = "games_{$system}_{$page}_{$limit}_{$search}";
        if (isset($this->cache[$cacheKey])) {
            error_log("Returning cached games for: " . $cacheKey);
            return $this->cache[$cacheKey];
        }

        $games = [];
        $gamelistPath = $this->gamesPath . '/' . $system . '/gamelist.xml';
        error_log("Looking for gamelist at: " . $gamelistPath);
        
        if (!file_exists($gamelistPath)) {
            error_log("gamelist.xml not found for system: " . $system);
            return [];
        }

        if (!is_readable($gamelistPath)) {
            error_log("gamelist.xml not readable for system: " . $system);
            return [];
        }

        $xml = simplexml_load_file($gamelistPath);
        if ($xml === false) {
            error_log("Failed to parse gamelist.xml for system: " . $system);
            return [];
        }

        $allGames = $xml->xpath('//game');
        
        // Filter games by name if search is provided
        if (!empty($search)) {
            $filteredGames = [];
            foreach ($allGames as $game) {
                $name = (string)$game->name;
                if (stripos($name, $search) !== false) {
                    $filteredGames[] = $game;
                }
            }
            $allGames = $filteredGames;
        }
        
        $totalGames = count($allGames);
        error_log("Total games found in XML: " . $totalGames);

        $offset = ($page - 1) * $limit;
        error_log("Using offset: " . $offset . " with limit: " . $limit);

        $gamesXml = array_slice($allGames, $offset, $limit);
        error_log("Games after slice: " . count($gamesXml));

        foreach ($gamesXml as $game) {
            $thumbnailPath = (string)$game->thumbnail;
            $imagePath = (string)$game->image;
            
            // Prefer thumbnail, fallback to image if thumbnail is not available
            $displayImage = !empty($thumbnailPath) ? $thumbnailPath : $imagePath;
            
            // If the path is relative, make it absolute
            if (!empty($displayImage) && strpos($displayImage, '/') !== 0) {
                $displayImage = '/' . $system . '/' . $displayImage;
            }

            $gameData = [
                'id' => (string)$game->path,
                'name' => (string)$game->name,
                'description' => (string)$game->desc,
                'image' => $displayImage,
                'system' => $system,
                'systemName' => $this->getSystemName($system)
            ];
            
            error_log("Adding game: " . json_encode($gameData));
            $games[] = $gameData;
        }

        error_log("Returning " . count($games) . " games");
        $this->cache[$cacheKey] = $games;
        return $games;
    }

    public function hasMoreGames(string $system, int $page, int $limit): bool
    {
        $gamelistPath = $this->gamesPath . '/' . $system . '/gamelist.xml';
        if (!file_exists($gamelistPath) || !is_readable($gamelistPath)) {
            return false;
        }

        $xml = simplexml_load_file($gamelistPath);
        if ($xml === false) {
            return false;
        }

        // Count only non-hidden games
        $visibleGames = 0;
        $allGames = $xml->xpath('//game');
        foreach ($allGames as $game) {
            // Skip games with hidden attribute set to true
            if (isset($game->hidden) && ((string)$game->hidden === 'true' || (string)$game->hidden === '1')) {
                continue;
            }
            $visibleGames++;
        }

        return $visibleGames > ($page * $limit);
    }

    public function searchGames(string $query, int $page = 1, int $limit = 12): array
    {
        if (empty($query)) {
            return [];
        }

        $cacheKey = "search_{$query}_{$page}_{$limit}";
        if (isset($this->cache[$cacheKey])) {
            return $this->cache[$cacheKey];
        }

        $systems = $this->getSystems();
        $results = [];

        foreach ($systems as $system) {
            $systemId = $system['id'];
            $gamelistPath = $this->gamesPath . '/' . $systemId . '/gamelist.xml';
            
            if (!file_exists($gamelistPath) || !is_readable($gamelistPath)) {
                continue;
            }

            $xml = simplexml_load_file($gamelistPath);
            if ($xml === false) {
                continue;
            }

            $games = $xml->xpath('//game');
            foreach ($games as $game) {
                $name = (string)$game->name;
                
                if (stripos($name, $query) !== false) {
                    $thumbnailPath = (string)$game->thumbnail;
                    $imagePath = (string)$game->image;
                    
                    // Prefer thumbnail, fallback to image if thumbnail is not available
                    $displayImage = !empty($thumbnailPath) ? $thumbnailPath : $imagePath;
                    
                    // If the path is relative, make it absolute
                    if (!empty($displayImage) && strpos($displayImage, '/') !== 0) {
                        $displayImage = '/' . $systemId . '/' . $displayImage;
                    }

                    $results[] = [
                        'id' => (string)$game->path,
                        'name' => $name,
                        'description' => (string)$game->desc,
                        'image' => $displayImage,
                        'system' => $systemId,
                        'systemName' => $this->getSystemName($systemId)
                    ];
                }
            }
        }

        // Sort results by relevance (exact matches first)
        usort($results, function($a, $b) use ($query) {
            $aNameContains = stripos($a['name'], $query) !== false;
            $bNameContains = stripos($b['name'], $query) !== false;
            
            if ($aNameContains && !$bNameContains) {
                return -1;
            } else if (!$aNameContains && $bNameContains) {
                return 1;
            } else {
                return 0;
            }
        });

        // Apply pagination
        $offset = ($page - 1) * $limit;
        $pagedResults = array_slice($results, $offset, $limit);

        $this->cache[$cacheKey] = $pagedResults;
        return $pagedResults;
    }

    public function hasMoreSearchResults(string $query, int $page, int $limit): bool
    {
        if (empty($query)) {
            return false;
        }

        // Get all search results (visible games only)
        $allResults = $this->searchGames($query, 1, PHP_INT_MAX);
        return count($allResults) > ($page * $limit);
    }

    public function getSystemName(string $systemId): string
    {
        $systemNames = [
            '3do' => '3DO',
            'amiga' => 'Amiga',
            'amigacd32' => 'Amiga CD32',
            'amstradcpc' => 'Amstrad CPC',
            'apple2' => 'Apple II',
            'arcade' => 'Arcade',
            'atari2600' => 'Atari 2600',
            'atari5200' => 'Atari 5200',
            'atari7800' => 'Atari 7800',
            'atarijaguar' => 'Atari Jaguar',
            'atarilynx' => 'Atari Lynx',
            'atarist' => 'Atari ST',
            'c64' => 'Commodore 64',
            'colecovision' => 'ColecoVision',
            'dreamcast' => 'Dreamcast',
            'fba' => 'Final Burn Alpha',
            'fds' => 'Famicom Disk System',
            'gameandwatch' => 'Game & Watch',
            'gamegear' => 'Game Gear',
            'gb' => 'Game Boy',
            'gba' => 'Game Boy Advance',
            'gbc' => 'Game Boy Color',
            'gc' => 'GameCube',
            'genesis' => 'Sega Genesis',
            'gw' => 'Game & Watch',
            'intellivision' => 'Intellivision',
            'mame' => 'MAME',
            'mastersystem' => 'Master System',
            'megadrive' => 'Mega Drive',
            'msx' => 'MSX',
            'msx1' => 'MSX1',
            'msx2' => 'MSX2',
            'n64' => 'Nintendo 64',
            'nds' => 'Nintendo DS',
            'neogeo' => 'Neo Geo',
            'neogeocd' => 'Neo Geo CD',
            'nes' => 'NES',
            'ngp' => 'Neo Geo Pocket',
            'ngpc' => 'Neo Geo Pocket Color',
            'pc' => 'PC',
            'pcengine' => 'PC Engine',
            'pcenginecd' => 'PC Engine CD',
            'pico' => 'Sega Pico',
            'pokemini' => 'Pokemon Mini',
            'psp' => 'PlayStation Portable',
            'psx' => 'PlayStation',
            'ps2' => 'PlayStation 2',
            'ps3' => 'PlayStation 3',
            'saturn' => 'Sega Saturn',
            'scummvm' => 'ScummVM',
            'sega32x' => 'Sega 32X',
            'segacd' => 'Sega CD',
            'sg1000' => 'SG-1000',
            'snes' => 'Super Nintendo',
            'supergrafx' => 'SuperGrafx',
            'tg16' => 'TurboGrafx-16',
            'tg16cd' => 'TurboGrafx-CD',
            'vectrex' => 'Vectrex',
            'virtualboy' => 'Virtual Boy',
            'wii' => 'Nintendo Wii',
            'wiiu' => 'Nintendo Wii U',
            'wonderswan' => 'WonderSwan',
            'wonderswancolor' => 'WonderSwan Color',
            'x68000' => 'X68000',
            'zxspectrum' => 'ZX Spectrum'
        ];

        return $systemNames[$systemId] ?? ucfirst($systemId);
    }

    public function getGameById(string $gameId): ?array
    {
        error_log("Getting game by ID: " . $gameId);
        
        // Clean up the game ID
        $cleanGameId = ltrim($gameId, './');
        error_log("Cleaned game ID: " . $cleanGameId);
        
        // The game ID is the path, which includes the system ID
        // Example format: /path/to/rom.zip or system/path/to/rom.zip
        
        $parts = explode('/', $cleanGameId);
        if (count($parts) < 1) {
            error_log("Invalid game ID format: " . $gameId);
            return null;
        }
        
        $systemId = $parts[0];
        error_log("System ID extracted: " . $systemId);
        
        // Check if system exists
        if (!$this->getSystem($systemId)) {
            error_log("System not found for ID: " . $systemId);
            return null;
        }
        
        $gamelistPath = $this->gamesPath . '/' . $systemId . '/gamelist.xml';
        error_log("Looking for gamelist at: " . $gamelistPath);
        
        if (!file_exists($gamelistPath) || !is_readable($gamelistPath)) {
            error_log("Gamelist not found or not readable for system: " . $systemId);
            return null;
        }
        
        $xml = simplexml_load_file($gamelistPath);
        if ($xml === false) {
            error_log("Failed to parse gamelist for system: " . $systemId);
            return null;
        }
        
        // Get the path portion without the system ID
        $pathWithoutSystem = implode('/', array_slice($parts, 1));
        error_log("Looking for game with path: " . $pathWithoutSystem);
        
        // Search for the game by path
        $found = null;
        foreach ($xml->xpath('//game') as $game) {
            $gamePath = (string)$game->path;
            $cleanGamePath = ltrim($gamePath, './');
            
            error_log("Comparing XML path: " . $gamePath . " (cleaned: " . $cleanGamePath . ")");
            error_log("With search path: " . $pathWithoutSystem . " or full: " . $cleanGameId);
            
            // Try multiple possible matches
            if ($cleanGamePath === $pathWithoutSystem || 
                $cleanGamePath === $cleanGameId || 
                $gamePath === './'. $pathWithoutSystem || 
                $gamePath === $pathWithoutSystem) {
                
                // Check if game is hidden
                if (isset($game->hidden) && ((string)$game->hidden === 'true' || (string)$game->hidden === '1')) {
                    error_log("Game found but is hidden: " . $gameId);
                    return null;
                }
                
                $found = $game;
                error_log("Game found with path: " . $gamePath);
                break;
            }
        }
        
        if (!$found) {
            error_log("Game not found with ID: " . $gameId);
            return null;
        }
        
        $thumbnailPath = (string)$found->thumbnail;
        $imagePath = (string)$found->image;
        
        error_log("Found thumbnail path: " . $thumbnailPath);
        error_log("Found image path: " . $imagePath);
        
        // Prefer thumbnail, fallback to image
        $displayImage = !empty($thumbnailPath) ? $thumbnailPath : $imagePath;
        
        // Clean up the image path
        $displayImage = ltrim($displayImage, './');
        
        // If path doesn't start with the system ID, prefix it
        if (!empty($displayImage) && strpos($displayImage, $systemId . '/') !== 0) {
            $displayImage = $systemId . '/' . $displayImage;
        }
        
        error_log("Final display image path: " . $displayImage);
        
        return [
            'id' => (string)$found->path,
            'name' => (string)$found->name,
            'description' => (string)$found->desc,
            'image' => $displayImage,
            'system' => $systemId
        ];
    }
} 