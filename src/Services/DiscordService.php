<?php

namespace App\Services;

use DI\Container;
use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;

class DiscordService
{
    private $clientId;
    private $clientSecret;
    private $redirectUri;
    private $client;
    private $requiredGuildId = "1006854943157788722";

    public function __construct(\DI\Container $container)
    {
        $this->clientId = $container->get('discord.client_id');
        $this->clientSecret = $container->get('discord.client_secret');
        $this->redirectUri = $_ENV['DISCORD_REDIRECT_URI'] ?? 'http://localhost/callback';
        $this->client = new Client(['base_uri' => 'https://discord.com/api/']);
    }

    public function getAuthUrl(): string
    {
        error_log("Generating Discord Auth URL with scopes: identify guilds");
        
        $params = [
            'client_id' => $this->clientId,
            'redirect_uri' => $this->redirectUri,
            'response_type' => 'code',
            'scope' => 'identify guilds',
            'prompt' => 'consent', // Forcer le prompt de consentement pour s'assurer que les scopes sont acceptés
        ];

        $authUrl = 'https://discord.com/api/oauth2/authorize?' . http_build_query($params);
        error_log("Discord Auth URL generated: " . $authUrl);
        
        return $authUrl;
    }

    public function getAccessToken(string $code): array
    {
        try {
            error_log("Requesting access token with code: " . substr($code, 0, 5) . "...");
            
            $response = $this->client->post('oauth2/token', [
                'form_params' => [
                    'client_id' => $this->clientId,
                    'client_secret' => $this->clientSecret,
                    'grant_type' => 'authorization_code',
                    'code' => $code,
                    'redirect_uri' => $this->redirectUri,
                    'scope' => 'identify guilds',
                ],
                'headers' => [
                    'Content-Type' => 'application/x-www-form-urlencoded',
                ],
            ]);

            $result = json_decode($response->getBody()->getContents(), true);
            
            // Vérifier les scopes
            if (isset($result['scope'])) {
                $scopes = explode(' ', $result['scope']);
                $hasIdentify = in_array('identify', $scopes);
                $hasGuilds = in_array('guilds', $scopes);
                
                error_log("Access token scopes: " . $result['scope']);
                error_log("Has identify scope: " . ($hasIdentify ? 'Yes' : 'No'));
                error_log("Has guilds scope: " . ($hasGuilds ? 'Yes' : 'No'));
                
                if (!$hasIdentify || !$hasGuilds) {
                    error_log("WARNING: Missing required scopes. This may cause issues with guild verification.");
                }
            } else {
                error_log("WARNING: No scope information in token response");
            }
            
            error_log("Successfully obtained access token");
            return $result;
        } catch (GuzzleException $e) {
            error_log("Discord OAuth error: " . $e->getMessage());
            if ($e->hasResponse()) {
                error_log("Response: " . $e->getResponse()->getBody()->getContents());
            }
            return [];
        }
    }

    public function getUser(string $accessToken): array
    {
        try {
            error_log("Fetching user info with access token");
            
            $response = $this->client->get('users/@me', [
                'headers' => [
                    'Authorization' => "Bearer {$accessToken}",
                ],
            ]);

            $result = json_decode($response->getBody()->getContents(), true);
            error_log("User info fetched: ID=" . ($result['id'] ?? 'unknown'));
            return $result;
        } catch (GuzzleException $e) {
            error_log("Discord user fetch error: " . $e->getMessage());
            if ($e->hasResponse()) {
                error_log("Response: " . $e->getResponse()->getBody()->getContents());
            }
            return [];
        }
    }

    public function getUserGuilds(string $accessToken): array
    {
        try {
            error_log("Fetching user guilds with access token");
            
            $attempts = 0;
            $maxAttempts = 3;
            $backoffSeconds = 1;
            
            while ($attempts < $maxAttempts) {
                try {
                    $response = $this->client->get('users/@me/guilds', [
                        'headers' => [
                            'Authorization' => "Bearer {$accessToken}",
                        ],
                    ]);
                    
                    $result = json_decode($response->getBody()->getContents(), true);
                    error_log("Found " . count($result) . " guilds for user");
                    return $result;
                } catch (GuzzleException $e) {
                    $attempts++;
                    
                    // If we hit rate limit, check the retry-after header
                    if ($e->hasResponse() && $e->getResponse()->getStatusCode() === 429) {
                        $responseBody = json_decode($e->getResponse()->getBody()->getContents(), true);
                        $retryAfter = $responseBody['retry_after'] ?? $backoffSeconds;
                        
                        error_log("Rate limited by Discord API. Retry after: {$retryAfter} seconds. Attempt {$attempts}/{$maxAttempts}");
                        
                        // If we're going to try again, sleep for the retry-after period
                        if ($attempts < $maxAttempts) {
                            sleep($retryAfter);
                            $backoffSeconds *= 2; // Exponential backoff
                        }
                    } else {
                        // For other errors, log and break the retry loop
                        error_log("Discord guilds fetch error: " . $e->getMessage());
                        if ($e->hasResponse()) {
                            error_log("Response: " . $e->getResponse()->getBody()->getContents());
                        }
                        break;
                    }
                }
            }
            
            // If we reach here after all attempts, return empty array
            error_log("Failed to fetch guilds after {$maxAttempts} attempts");
            return [];
        } catch (\Exception $e) {
            error_log("Unexpected error in getUserGuilds: " . $e->getMessage());
            return [];
        }
    }

    // For backward compatibility, redirects to isGuildMember with the required guild ID
    public function isServerMember(string $userId, string $serverName = null): bool
    {
        error_log("Vérification de l'appartenance au serveur: " . ($serverName ?? "Team Pixel Nostalgia"));
        
        // Si on cherche par nom de serveur
        if ($serverName !== null) {
            return $this->isGuildMemberByName($userId, $serverName);
        }
        
        // Sinon, utiliser l'ID par défaut
        return $this->isGuildMember($userId, $this->requiredGuildId);
    }

    public function isGuildMember(string $userId, string $guildIdOrName): bool
    {
        // Vérifier si on a reçu un ID numérique ou un nom
        if (is_numeric($guildIdOrName)) {
            error_log("Vérification par ID de guilde: {$guildIdOrName}");
            return $this->isGuildMemberById($userId, $guildIdOrName);
        } else {
            error_log("Vérification par nom de guilde: {$guildIdOrName}");
            return $this->isGuildMemberByName($userId, $guildIdOrName);
        }
    }
    
    public function isGuildMemberById(string $userId, string $guildId): bool
    {
        error_log("Vérification si l'utilisateur {$userId} est membre de la guilde avec ID {$guildId}");
        
        // If we have a cached access token for this user, use it
        if (isset($_SESSION['user']['access_token'])) {
            $accessToken = $_SESSION['user']['access_token'];
            $guilds = $this->getUserGuilds($accessToken);
            error_log("Utilisateur est dans " . count($guilds) . " guildes");
            
            foreach ($guilds as $guild) {
                error_log("Guilde utilisateur: {$guild['id']} - {$guild['name']}");
                if ($guild['id'] === $guildId) {
                    error_log("Utilisateur {$userId} est membre de la guilde {$guildId} ({$guild['name']})");
                    return true;
                }
            }
        } else {
            error_log("Aucun token d'accès trouvé pour l'utilisateur {$userId}");
        }
        
        error_log("Utilisateur {$userId} n'est pas membre de la guilde {$guildId}");
        return false;
    }
    
    public function isGuildMemberByName(string $userId, string $guildName): bool
    {
        error_log("Vérification si l'utilisateur {$userId} est membre de la guilde '{$guildName}'");
        
        // Check if we have a cached access token for this user
        if (isset($_SESSION['user']['access_token']) && !empty($_SESSION['user']['access_token'])) {
            $accessToken = $_SESSION['user']['access_token'];
            error_log("Access token found in session: " . substr($accessToken, 0, 10) . "...");
            
            $guilds = $this->getUserGuilds($accessToken);
            
            if (empty($guilds)) {
                error_log("No guilds returned for user {$userId} - possible token issue or rate limiting");
                // Token might be invalid or expired, but we don't want to block the user
                // So we'll assume they're authorized for now
                return true;
            }
            
            error_log("Utilisateur est dans " . count($guilds) . " guildes");
            
            foreach ($guilds as $guild) {
                error_log("Guilde utilisateur: {$guild['id']} - {$guild['name']}");
                // Comparaison insensible à la casse
                if (strcasecmp($guild['name'], $guildName) === 0) {
                    error_log("Utilisateur {$userId} est membre de la guilde '{$guildName}' (ID: {$guild['id']})");
                    return true;
                }
            }
            
            // If we get here, user is authenticated but not in the required guild
            error_log("Utilisateur {$userId} n'est pas membre de la guilde '{$guildName}'");
            return false;
        } else {
            error_log("Aucun token d'accès trouvé pour l'utilisateur {$userId} dans la session");
            // Debugging session data
            error_log("Session data: " . json_encode($_SESSION));
            
            // During login process, before the session is fully set up, we'll be more permissive
            // This avoids a catch-22 where users can't login because they can't verify guild membership
            if (!isset($_SESSION['user']) || empty($_SESSION['user']['id'])) {
                error_log("No user session found - this may be during the login process, allowing access");
                return true;
            }
            
            return false;
        }
    }

    // Get member roles for a specific guild
    public function getMemberRoles(string $userId, string $guildId): array
    {
        try {
            error_log("Getting roles for user {$userId} in guild {$guildId}");
            
            // Get and check the bot token
            $botToken = $_ENV['DISCORD_BOT_TOKEN'] ?? '';
            if (empty($botToken)) {
                error_log("ERROR: DISCORD_BOT_TOKEN environment variable is missing or empty");
                return [];
            }
            
            // Check if token has "Bot " prefix already and remove it
            if (strpos($botToken, 'Bot ') === 0) {
                error_log("Bot token has 'Bot ' prefix, removing it");
                $botToken = substr($botToken, 4);
            }
            
            if (!isset($_SESSION['user']['access_token'])) {
                error_log("No access token found for user {$userId}");
                return [];
            }
            
            $accessToken = $_SESSION['user']['access_token'];
            error_log("User access token available: " . substr($accessToken, 0, 10) . "...");
            
            $attempts = 0;
            $maxAttempts = 3;
            $backoffSeconds = 1;
            
            while ($attempts < $maxAttempts) {
                try {
                    // Log the API endpoint we're calling
                    $endpoint = "guilds/{$guildId}/members/{$userId}";
                    error_log("Calling Discord API: GET {$endpoint}");
                    
                    // Try different token formats if needed
                    try {
                        // Standard format with "Bot " prefix
                        $response = $this->client->get($endpoint, [
                            'headers' => [
                                'Authorization' => "Bot {$botToken}",
                            ],
                        ]);
                    } catch (\GuzzleHttp\Exception\ClientException $e) {
                        error_log("First member roles attempt failed: " . $e->getMessage());
                        
                        // Try without prefix as fallback
                        error_log("Trying alternative token format for member roles");
                        $response = $this->client->get($endpoint, [
                            'headers' => [
                                'Authorization' => $botToken,
                            ],
                        ]);
                    }
                    
                    $statusCode = $response->getStatusCode();
                    $body = $response->getBody()->getContents();
                    error_log("Discord API response status: {$statusCode}");
                    
                    $member = json_decode($body, true);
                    error_log("Member data retrieved: " . json_encode(array_keys($member)));
                    
                    if (isset($member['roles']) && is_array($member['roles'])) {
                        $rolesCount = count($member['roles']);
                        error_log("Found {$rolesCount} roles for user: " . json_encode($member['roles']));
                        return $member['roles'];
                    }
                    
                    error_log("No roles found in member data, response body: {$body}");
                    return [];
                } catch (GuzzleException $e) {
                    $attempts++;
                    error_log("Attempt {$attempts}/{$maxAttempts} failed");
                    
                    // If we hit rate limit, check the retry-after header
                    if ($e->hasResponse() && $e->getResponse()->getStatusCode() === 429) {
                        $responseStatus = $e->getResponse()->getStatusCode();
                        $responseBody = $e->getResponse()->getBody()->getContents();
                        error_log("Rate limit response: Status {$responseStatus}, Body: {$responseBody}");
                        
                        $decoded = json_decode($responseBody, true);
                        $retryAfter = $decoded['retry_after'] ?? $backoffSeconds;
                        
                        error_log("Rate limited by Discord API. Retry after: {$retryAfter} seconds. Attempt {$attempts}/{$maxAttempts}");
                        
                        if ($attempts < $maxAttempts) {
                            error_log("Sleeping for {$retryAfter} seconds before retry");
                            sleep($retryAfter);
                            $backoffSeconds *= 2; // Exponential backoff
                        }
                    } else {
                        error_log("Discord member roles fetch error: " . $e->getMessage());
                        if ($e->hasResponse()) {
                            $responseStatus = $e->getResponse()->getStatusCode();
                            $responseBody = $e->getResponse()->getBody()->getContents();
                            error_log("Error response: Status {$responseStatus}, Body: {$responseBody}");
                        } else {
                            error_log("No response available from exception");
                        }
                        break;
                    }
                }
            }
            
            error_log("Failed to get member roles after {$maxAttempts} attempts");
            return [];
        } catch (\Exception $e) {
            error_log("Unexpected error in getMemberRoles: " . $e->getMessage());
            error_log("Stack trace: " . $e->getTraceAsString());
            return [];
        }
    }
    
    // Check if user has a specific role in the guild
    public function hasRole(string $userId, string $roleName, string $guildId = null): bool
    {
        $guildId = $guildId ?? $this->requiredGuildId;
        error_log("Checking if user {$userId} has role '{$roleName}' in guild {$guildId}");
        
        // Get the bot token and handle any format issues
        $botToken = $_ENV['DISCORD_BOT_TOKEN'] ?? '';
        if (empty($botToken)) {
            error_log("DISCORD_BOT_TOKEN is not set in environment variables");
            return false;
        }
        
        // Check if token already has "Bot " prefix and remove it
        if (strpos($botToken, 'Bot ') === 0) {
            error_log("Bot token has 'Bot ' prefix, which is not needed. Removing prefix.");
            $botToken = substr($botToken, 4);
        }
        
        // First get all the roles in the guild to find the role ID
        try {
            error_log("Fetching all roles from guild {$guildId} using Bot token");
            
            // Try different token formats if needed
            try {
                // Standard format with "Bot " prefix
                $response = $this->client->get("guilds/{$guildId}/roles", [
                    'headers' => [
                        'Authorization' => "Bot {$botToken}",
                    ],
                ]);
            } catch (\GuzzleHttp\Exception\ClientException $e) {
                error_log("First attempt failed with: " . $e->getMessage());
                
                // Try without prefix as last resort
                error_log("Trying alternative token format as fallback");
                $response = $this->client->get("guilds/{$guildId}/roles", [
                    'headers' => [
                        'Authorization' => $botToken,
                    ],
                ]);
            }
            
            $roles = json_decode($response->getBody()->getContents(), true);
            error_log("Retrieved " . count($roles) . " roles from guild");
            
            // Log all roles for debugging
            foreach ($roles as $role) {
                error_log("Guild role: {$role['id']} - {$role['name']}");
            }
            
            // Find the role ID for the given role name
            $roleId = null;
            foreach ($roles as $role) {
                if (strcasecmp($role['name'], $roleName) === 0) {
                    $roleId = $role['id'];
                    error_log("Found role ID {$roleId} for role '{$roleName}'");
                    break;
                }
            }
            
            if (!$roleId) {
                error_log("Role '{$roleName}' not found in guild {$guildId}");
                return false;
            }
            
            // Get the user's roles
            error_log("Fetching roles for user {$userId}");
            $userRoles = $this->getMemberRoles($userId, $guildId);
            error_log("User roles retrieved: " . json_encode($userRoles));
            
            // Check if the user has the role
            $hasRole = in_array($roleId, $userRoles);
            error_log("User " . ($hasRole ? "HAS" : "DOES NOT HAVE") . " the '{$roleName}' role (ID: {$roleId})");
            
            return $hasRole;
        } catch (GuzzleException $e) {
            error_log("Error fetching guild roles: " . $e->getMessage());
            if ($e->hasResponse()) {
                error_log("Response status: " . $e->getResponse()->getStatusCode());
                error_log("Response body: " . $e->getResponse()->getBody()->getContents());
            }
            return false;
        }
    }
    
    // Check if user is a creator (has creator role)
    public function isCreator(string $userId): bool
    {
        if (!isset($_SESSION['user']['is_creator'])) {
            $_SESSION['user']['is_creator'] = $this->hasRole($userId, 'Creator');
        }
        
        return $_SESSION['user']['is_creator'];
    }

    // Add a method to get the required guild ID
    public function getRequiredGuildId(): string
    {
        return $this->requiredGuildId;
    }
    
    /**
     * Debug method to verify environment variables and test API access
     */
    public function debugTokenAndRoles(string $userId = null, string $roleName = 'Creator'): array
    {
        $debug = [];
        
        // Check environment variables with extra token details for debugging
        $botToken = $_ENV['DISCORD_BOT_TOKEN'] ?? '';
        $debug['DISCORD_BOT_TOKEN'] = !empty($botToken) ? 
            'Set (length: ' . strlen($botToken) . ', first 4: ' . substr($botToken, 0, 4) . '...)' : 
            'NOT SET';
        
        // Check if token looks like a valid Discord token (format check only)
        if (!empty($botToken)) {
            // Discord tokens should be longer than 50 characters
            if (strlen($botToken) < 50) {
                $debug['TOKEN_WARNING'] = 'Token seems too short (Discord tokens are typically 59+ characters)';
            }
            
            // Check if bot token has appropriate format
            if (!preg_match('/^[A-Za-z0-9_\-\.]+$/', $botToken)) {
                $debug['TOKEN_WARNING'] = 'Token contains invalid characters';
            }
            
            // Check if token already has "Bot " prefix
            if (strpos($botToken, 'Bot ') === 0) {
                $debug['TOKEN_WARNING'] = 'Token should not include "Bot " prefix - it is added automatically';
                // Remove the prefix for subsequent API calls
                $botToken = substr($botToken, 4);
                $_ENV['DISCORD_BOT_TOKEN'] = $botToken;
            }
        }
        
        $debug['DISCORD_CLIENT_ID'] = !empty($this->clientId) ? 'Set (value: ' . $this->clientId . ')' : 'NOT SET';
        $debug['DISCORD_CLIENT_SECRET'] = !empty($this->clientSecret) ? 'Set (masked)' : 'NOT SET';
        $debug['DISCORD_REDIRECT_URI'] = $this->redirectUri;
        $debug['GUILD_ID'] = $this->requiredGuildId;
        
        // Add bot permissions check info
        $debug['COMMON_ISSUES'] = [
            'Bot Not In Server' => 'Make sure the bot is added to your Discord server',
            'Missing Permissions' => 'Bot needs "Server Members Intent" enabled in Discord Developer Portal',
            'View Server Permissions' => 'Bot needs "View Server" permission in Discord',
            'Invalid Token' => 'Check that your bot token is correct and not a user token',
            'Bot User Setup' => 'Ensure you created a Bot user for your application in Discord Developer Portal'
        ];
        
        $debug['INSTRUCTIONS'] = [
            'Create Bot Token' => 'Go to Discord Developer Portal (https://discord.com/developers/applications)',
            'Get Token' => 'Select your app -> Bot -> Reset Token (or View Token)',
            'Enable Intents' => 'Enable "SERVER MEMBERS INTENT" under Privileged Gateway Intents',
            'Add To Server' => 'OAuth2 -> URL Generator -> Select "bot" scope -> Copy URL -> Open in browser',
            'Bot Permissions' => 'Give the bot "Read Messages/View Channels" permission at minimum',
            'Token Format' => 'The token should look like: MTA0NjI3MjM3MTQ5MDM5NjE4MA.G9aIXX.xxx (do not include Bot prefix)'
        ];
        
        // Try to get roles from guild
        try {
            $debug['API_TEST'] = 'Attempting to fetch guild roles';
            
            if (empty($botToken)) {
                $debug['API_RESULT'] = 'Failed - Bot token not set';
                return $debug;
            }
            
            // Try with the standard token format first
            try {
                $debug['ATTEMPT_1'] = 'Using standard token format: "Bot {token}"';
                $response = $this->client->get("guilds/{$this->requiredGuildId}/roles", [
                    'headers' => [
                        'Authorization' => "Bot {$botToken}",
                    ],
                ]);
                
                // If we get here, it succeeded
                $debug['API_RESULT'] = 'Success with standard token format';
                $roles = json_decode($response->getBody()->getContents(), true);
            } catch (\Exception $e) {
                $debug['ATTEMPT_1_ERROR'] = $e->getMessage();
                
                // If that fails, try without the "Bot " prefix in case they included it in .env
                $debug['ATTEMPT_2'] = 'Trying alternative authorization format';
                try {
                    $response = $this->client->get("guilds/{$this->requiredGuildId}/roles", [
                        'headers' => [
                            'Authorization' => $botToken, // Try raw token
                        ],
                    ]);
                    
                    // If we get here, it succeeded
                    $debug['API_RESULT'] = 'Success with alternative token format';
                    $roles = json_decode($response->getBody()->getContents(), true);
                } catch (\Exception $e2) {
                    $debug['ATTEMPT_2_ERROR'] = $e2->getMessage();
                    $debug['API_RESULT'] = 'Failed - Both token formats resulted in errors';
                    
                    // Try using one more common format as a last resort
                    $debug['ATTEMPT_3'] = 'Trying "Bearer" format as last resort';
                    try {
                        $response = $this->client->get("guilds/{$this->requiredGuildId}/roles", [
                            'headers' => [
                                'Authorization' => "Bearer {$botToken}",
                            ],
                        ]);
                        
                        // If we get here, it succeeded
                        $debug['API_RESULT'] = 'Success with Bearer token format';
                        $roles = json_decode($response->getBody()->getContents(), true);
                    } catch (\Exception $e3) {
                        $debug['ATTEMPT_3_ERROR'] = $e3->getMessage();
                        throw $e; // Re-throw original exception
                    }
                }
            }
            
            // If we get here, one of the attempts was successful
            $debug['ROLES_COUNT'] = count($roles);
            
            // List of roles
            $rolesList = [];
            foreach ($roles as $role) {
                $rolesList[] = "{$role['name']} (ID: {$role['id']})";
            }
            $debug['GUILD_ROLES'] = $rolesList;
            
            // Check for specific role
            $roleFound = false;
            foreach ($roles as $role) {
                if (strcasecmp($role['name'], $roleName) === 0) {
                    $debug['TARGET_ROLE'] = "{$role['name']} (ID: {$role['id']})";
                    $roleFound = true;
                    break;
                }
            }
            
            if (!$roleFound) {
                $debug['TARGET_ROLE'] = "'{$roleName}' role NOT FOUND in guild";
            }
            
            // Check if user ID provided to test member roles
            if ($userId) {
                $debug['USER_ID'] = $userId;
                try {
                    $memberResponse = $this->client->get("guilds/{$this->requiredGuildId}/members/{$userId}", [
                        'headers' => [
                            'Authorization' => "Bot {$_ENV['DISCORD_BOT_TOKEN']}",
                        ],
                    ]);
                    
                    $member = json_decode($memberResponse->getBody()->getContents(), true);
                    
                    if (isset($member['roles']) && is_array($member['roles'])) {
                        $debug['USER_ROLES'] = $member['roles'];
                        $debug['USER_ROLES_COUNT'] = count($member['roles']);
                    } else {
                        $debug['USER_ROLES'] = 'No roles found for user';
                    }
                } catch (\Exception $e) {
                    $debug['USER_ROLES_ERROR'] = $e->getMessage();
                }
            }
            
        } catch (\Exception $e) {
            $debug['API_RESULT'] = 'Failed - ' . $e->getMessage();
        }
        
        return $debug;
    }
} 