<?php /* Layout is included by the RenderTrait */ ?>

<!-- Link to external CSS -->
<link rel="stylesheet" href="/assets/css/systems.css">

<h1 class="page-title">Game Systems</h1>

<div class="systems-grid">
    <?php foreach ($systems as $system): ?>
        <a href="/system/<?php echo htmlspecialchars($system['id']); ?>" class="system-card">
            <?php if (isset($system['image']) && !empty($system['image'])): ?>
                <div class="system-image">
                    <img src="<?php echo htmlspecialchars($system['image']); ?>" alt="<?php echo htmlspecialchars($system['name']); ?>" loading="lazy">
                </div>
            <?php endif; ?>
            
            <div class="system-info">
                <h2 class="system-name"><?php echo htmlspecialchars($system['name']); ?></h2>
                <p class="system-games-count"><?php echo $system['gameCount']; ?> games</p>
            </div>
        </a>
    <?php endforeach; ?>
</div> 