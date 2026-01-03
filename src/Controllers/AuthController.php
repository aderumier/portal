<?php

namespace App\Controllers;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use App\Services\DiscordService;
use DI\Container;
use App\Traits\RenderTrait;

class AuthController
{
    use RenderTrait;
    
    private $discordService;

    public function __construct(\DI\Container $container)
    {
        $this->discordService = $container->get(DiscordService::class);
    }

    public function login(Request $request, Response $response): Response
    {
        $authUrl = $this->discordService->getAuthUrl();
        return $response->withHeader('Location', $authUrl)->withStatus(302);
    }

    public function callback(Request $request, Response $response): Response
    {
        $queryParams = $request->getQueryParams();
        $code = $queryParams['code'] ?? null;
        
        error_log("Auth callback received with code: " . substr($code, 0, 5) . "...");

        if (!$code) {
            error_log("Error: No code provided in callback");
            return $response->withHeader('Location', '/')->withStatus(302);
        }

        try {
            // Exchange code for access token
            $tokenData = $this->discordService->getAccessToken($code);
            
            if (!isset($tokenData['access_token']) || empty($tokenData['access_token'])) {
                error_log("Failed to get access token: " . json_encode($tokenData));
                return $response->withHeader('Location', '/')->withStatus(302);
            }
            
            $accessToken = $tokenData['access_token'];
            error_log("Access token received: " . substr($accessToken, 0, 10) . "... Scope: " . ($tokenData['scope'] ?? 'not_specified'));

            // Get user info
            $user = $this->discordService->getUser($accessToken);
            
            if (!isset($user['id']) || empty($user['id'])) {
                error_log("Failed to get user data: " . json_encode($user));
                return $response->withHeader('Location', '/')->withStatus(302);
            }
            
            error_log("User data received: " . $user['username'] . " (ID: " . $user['id'] . ")");

            // Initialize the session with user info and token first
            // This ensures the token is available for guild membership check
            $_SESSION['user'] = [
                'id' => $user['id'],
                'username' => $user['username'],
                'avatar' => $user['avatar'],
                'access_token' => $accessToken,
                'is_guild_member' => false, // Default to false until verified
                'is_creator' => false
            ];
            
            session_write_close(); // Ensure session is written
            session_start(); // Reopen for further modifications

            // Check if user is a member of the required guild
            $requiredGuildName = "Team Pixel Nostalgia";
            
            // Check guild membership
            error_log("Checking if user is a member of guild: " . $requiredGuildName);
            $isGuildMember = $this->discordService->isGuildMemberByName($user['id'], $requiredGuildName);
            error_log("Guild membership check result: " . ($isGuildMember ? "IS member" : "NOT a member"));
            
            // Check if user has the creator role
            $isCreator = false;
            if ($isGuildMember) {
                error_log("Checking if user has the Creator role (ID: {$user['id']})");
                // Get guild ID through the accessor method
                $guildId = $this->discordService->getRequiredGuildId();
                error_log("Guild ID for role check: " . $guildId);
                
                // Log all roles available in the guild first
                $this->logGuildRoles();
                
                $isCreator = $this->discordService->hasRole($user['id'], 'Creator');
                error_log("Creator role check result: " . ($isCreator ? "IS creator" : "NOT a creator"));
            }
            
            // Update guild membership and creator status in session
            $_SESSION['user']['is_guild_member'] = $isGuildMember;
            $_SESSION['user']['is_creator'] = $isCreator;

            if (!$isGuildMember) {
                error_log("User is not a guild member, redirecting to unauthorized");
                return $response->withHeader('Location', '/unauthorized')->withStatus(302);
            }

            error_log("Authentication successful, redirecting to systems page");
            return $response->withHeader('Location', '/systems')->withStatus(302);
        } catch (\Exception $e) {
            error_log("Error during Discord authentication: " . $e->getMessage());
            error_log("Error trace: " . $e->getTraceAsString());
            return $response->withHeader('Location', '/')->withStatus(302);
        }
    }

    public function logout(Request $request, Response $response): Response
    {
        unset($_SESSION['user']);
        return $response->withHeader('Location', '/')->withStatus(302);
    }

    public function unauthorized(Request $request, Response $response): Response
    {
        $content = $this->render('unauthorized.php');
        $response->getBody()->write($content);
        return $response->withHeader('Content-Type', 'text/html');
    }

    /**
     * Get the Discord guild ID used for role checks
     */
    private function getDiscordGuildId(): string
    {
        return $this->discordService->getRequiredGuildId();
    }

    /**
     * Log all roles available in the guild
     */
    private function logGuildRoles(): void
    {
        try {
            error_log("Fetching all guild roles for debugging");
            
            if (empty($_ENV['DISCORD_BOT_TOKEN'])) {
                error_log("ERROR: Bot token not set in environment variables");
                return;
            }
            
            $guildId = $this->getDiscordGuildId();
            $client = new \GuzzleHttp\Client(['base_uri' => 'https://discord.com/api/']);
            
            $response = $client->get("guilds/{$guildId}/roles", [
                'headers' => [
                    'Authorization' => "Bot {$_ENV['DISCORD_BOT_TOKEN']}",
                ],
            ]);
            
            $roles = json_decode($response->getBody()->getContents(), true);
            error_log("Guild roles information (Total: " . count($roles) . "):");
            
            foreach ($roles as $role) {
                error_log("Role: '{$role['name']}' (ID: {$role['id']})");
            }
        } catch (\Exception $e) {
            error_log("Error fetching guild roles for debug: " . $e->getMessage());
        }
    }
} 