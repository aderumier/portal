<?php

namespace App\Services;

use GuzzleHttp\Client;

class AuthService
{
    private $clientId;
    private $clientSecret;
    private $redirectUri;
    private $httpClient;

    public function __construct(string $clientId, string $clientSecret, string $redirectUri)
    {
        $this->clientId = $clientId;
        $this->clientSecret = $clientSecret;
        $this->redirectUri = $redirectUri;
        $this->httpClient = new Client();
    }

    public function getDiscordClientId(): string
    {
        return $this->clientId;
    }

    public function getRedirectUri(): string
    {
        return $this->redirectUri;
    }

    public function handleDiscordCallback(string $code): array
    {
        $tokenResponse = $this->httpClient->post('https://discord.com/api/oauth2/token', [
            'form_params' => [
                'client_id' => $this->clientId,
                'client_secret' => $this->clientSecret,
                'grant_type' => 'authorization_code',
                'code' => $code,
                'redirect_uri' => $this->redirectUri
            ]
        ]);

        $tokenData = json_decode($tokenResponse->getBody()->getContents(), true);
        $accessToken = $tokenData['access_token'];

        $userResponse = $this->httpClient->get('https://discord.com/api/users/@me', [
            'headers' => [
                'Authorization' => "Bearer {$accessToken}"
            ]
        ]);

        $userData = json_decode($userResponse->getBody()->getContents(), true);

        return [
            'id' => $userData['id'],
            'username' => $userData['username'],
            'discriminator' => $userData['discriminator'],
            'avatar' => $userData['avatar'],
            'email' => $userData['email'] ?? null
        ];
    }

    public function setUserSession(array $user): void
    {
        $_SESSION['user'] = $user;
    }

    public function clearUserSession(): void
    {
        unset($_SESSION['user']);
    }

    public function isAuthenticated(): bool
    {
        return isset($_SESSION['user']);
    }

    public function getCurrentUser(): ?array
    {
        return $_SESSION['user'] ?? null;
    }
} 