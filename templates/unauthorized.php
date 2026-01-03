<?php /* Layout is included by the RenderTrait */ ?>

<!-- Link to external CSS -->
<link rel="stylesheet" href="/assets/css/unauthorized.css">

<div class="unauthorized-container">
    <div class="unauthorized-content">
        <h1>Access Denied</h1>
        
        <?php if (!isset($_SESSION['user'])): ?>
            <!-- Not logged in -->
            <p>You need to login with Discord to access this content.</p>
            <div class="unauthorized-actions">
                <a href="/login" class="btn btn-primary">Login with Discord</a>
            </div>
        <?php elseif (!isset($_SESSION['user']['is_guild_member']) || !$_SESSION['user']['is_guild_member']): ?>
            <!-- Logged in but not a guild member -->
            <p>You need to be a member of our Discord server "Team Pixel Nostalgia" to access this content.</p>
            <div class="unauthorized-actions">
                <a href="https://discord.gg/your-invite-link" class="btn btn-secondary" target="_blank">Join Team Pixel Nostalgia</a>
                <a href="/logout" class="btn btn-primary">Logout</a>
            </div>
        <?php else: ?>
            <!-- Guild member but not a creator -->
            <p>You need to have the "creator" role in our Discord server to access the download features.</p>
            <div class="unauthorized-actions">
                <a href="/" class="btn btn-secondary">Back to Home</a>
                <a href="/logout" class="btn btn-primary">Logout</a>
            </div>
        <?php endif; ?>
    </div>
</div> 