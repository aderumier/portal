<?php /* Layout is included by the RenderTrait */ ?>

<!-- Link to external CSS -->
<link rel="stylesheet" href="/assets/css/home.css">

<div class="hero">
    <div class="hero-content">
        <h1>Welcome to Pixel Nostalgia</h1>
        <div class="hero-image">
            <img src="https://pixelnostalgia.github.io/media/posts/4/responsive/background-xl.webp" alt="Pixel Nostalgia Background" loading="lazy">
        </div>
        <p>Your retro game library for Team Pixel Nostalgia members</p>
        <?php if (!isset($_SESSION['user'])): ?>
            <a href="/login" class="hero-cta">Login with Discord</a>
        <?php else: ?>
            <a href="/systems" class="hero-cta">Browse Games</a>
        <?php endif; ?>
    </div>
</div>

<div class="home-features">
    <div class="feature">
        <i class="fas fa-gamepad"></i>
        <h2>Extensive Collection</h2>
        <p>Browse through our curated collection of retro games across multiple systems</p>
    </div>
    <div class="feature">
        <i class="fas fa-download"></i>
        <h2>Download Access</h2>
        <p>Creators can download games directly through our secure download system</p>
    </div>
    <div class="feature">
        <i class="fas fa-search"></i>
        <h2>Advanced Search</h2>
        <p>Find your favorite games quickly with our powerful search functionality</p>
    </div>
</div> 