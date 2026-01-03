<?php
// Check if user is logged in and has creator role
if (!isset($_SESSION['user']) || !isset($_SESSION['user']['is_creator']) || !$_SESSION['user']['is_creator']) {
    header('Location: /unauthorized');
    exit;
}
?>

<!-- Link to external CSS -->
<link rel="stylesheet" href="/assets/css/downloads.css">

<div class="downloads-header">
    <h1>My Downloads</h1>
    <div class="downloads-actions">
        <div class="view-toggle">
            <button id="grid-view" class="view-btn active" title="Grid View">
                <i class="fas fa-th-large"></i>
            </button>
            <button id="table-view" class="view-btn" title="Table View">
                <i class="fas fa-list"></i>
            </button>
        </div>
        <button id="clear-queue" class="clear-queue-btn">Clear Queue</button>
    </div>
</div>

<div id="downloads-container">
    <!-- Grid View -->
    <div class="downloads-grid active-view">
        <?php if (empty($queue)): ?>
            <div class="no-downloads">No games in your download queue</div>
        <?php else: ?>
            <?php foreach ($queue as $item): ?>
                <div class="download-card" data-game-id="<?php echo htmlspecialchars($item['game_id']); ?>">
                    <?php if (!empty($item['image'])): ?>
                        <div class="download-card-image">
                            <img src="/media/<?php echo htmlspecialchars($item['image']); ?>" alt="<?php echo htmlspecialchars($item['game_name']); ?>" loading="lazy">
                        </div>
                    <?php endif; ?>
                    <div class="download-card-content">
                        <h3 class="game-title"><?php echo htmlspecialchars($item['game_name']); ?></h3>
                        <div class="game-meta">
                            <span class="system-tag"><?php echo htmlspecialchars($item['system_name']); ?></span>
                            <span class="status-tag <?php echo htmlspecialchars($item['status']); ?>"><?php echo ucfirst(htmlspecialchars($item['status'])); ?></span>
                        </div>
                        <div class="download-actions">
                            <button class="remove-download-btn" data-game-id="<?php echo htmlspecialchars($item['game_id']); ?>">Remove</button>
                        </div>
                    </div>
                </div>
            <?php endforeach; ?>
        <?php endif; ?>
    </div>

    <!-- Table View -->
    <div class="downloads-table">
        <?php if (empty($queue)): ?>
            <div class="no-downloads">No games in your download queue</div>
        <?php else: ?>
            <table>
                <thead>
                    <tr>
                        <th>Game</th>
                        <th>System</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($queue as $item): ?>
                        <tr data-game-id="<?php echo htmlspecialchars($item['game_id']); ?>">
                            <td class="game-info">
                                <?php if (!empty($item['image'])): ?>
                                    <img class="table-thumbnail" src="/media/<?php echo htmlspecialchars($item['image']); ?>" alt="<?php echo htmlspecialchars($item['game_name']); ?>" loading="lazy">
                                <?php endif; ?>
                                <span><?php echo htmlspecialchars($item['game_name']); ?></span>
                            </td>
                            <td><?php echo htmlspecialchars($item['system_name']); ?></td>
                            <td><span class="status-tag <?php echo htmlspecialchars($item['status']); ?>"><?php echo ucfirst(htmlspecialchars($item['status'])); ?></span></td>
                            <td>
                                <button class="remove-download-btn" data-game-id="<?php echo htmlspecialchars($item['game_id']); ?>">Remove</button>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        <?php endif; ?>
    </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', () => {
    // View toggle functionality
    const gridView = document.getElementById('grid-view');
    const tableView = document.getElementById('table-view');
    const gridContainer = document.querySelector('.downloads-grid');
    const tableContainer = document.querySelector('.downloads-table');

    gridView.addEventListener('click', () => {
        gridView.classList.add('active');
        tableView.classList.remove('active');
        gridContainer.classList.add('active-view');
        tableContainer.classList.remove('active-view');
        localStorage.setItem('downloads-view', 'grid');
    });

    tableView.addEventListener('click', () => {
        tableView.classList.add('active');
        gridView.classList.remove('active');
        tableContainer.classList.add('active-view');
        gridContainer.classList.remove('active-view');
        localStorage.setItem('downloads-view', 'table');
    });

    // Restore user's preferred view
    const savedView = localStorage.getItem('downloads-view');
    if (savedView === 'table') {
        tableView.click();
    }

    // Handle remove download
    document.querySelectorAll('.remove-download-btn').forEach(button => {
        button.addEventListener('click', async (e) => {
            const gameId = e.target.dataset.gameId;
            console.log('Removing game with ID:', gameId);
            
            try {
                // Double encode the gameId to handle slashes correctly
                const encodedGameId = encodeURIComponent(encodeURIComponent(gameId));
                console.log('Encoded game ID:', encodedGameId);
                
                const response = await fetch(`/api/download/queue/${encodedGameId}`, {
                    method: 'DELETE',
                    credentials: 'same-origin' // Include cookies in the request
                });
                
                console.log('Remove response status:', response.status);
                
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `Failed to remove game (Status: ${response.status})`);
                }

                // Remove the card/row from both views
                const card = document.querySelector(`.download-card[data-game-id="${gameId}"]`);
                const row = document.querySelector(`tr[data-game-id="${gameId}"]`);
                if (card) card.remove();
                if (row) row.remove();

                // If no more downloads, show the empty message in both views
                const remainingCards = document.querySelectorAll('.download-card');
                if (remainingCards.length === 0) {
                    const emptyMessage = '<div class="no-downloads">No games in your download queue</div>';
                    gridContainer.innerHTML = emptyMessage;
                    tableContainer.innerHTML = emptyMessage;
                }
            } catch (error) {
                console.error('Error removing game from queue:', error);
                alert('Failed to remove game from queue: ' + error.message);
            }
        });
    });

    // Handle clear queue
    const clearQueueBtn = document.getElementById('clear-queue');
    if (clearQueueBtn) {
        clearQueueBtn.addEventListener('click', async () => {
            if (!confirm('Are you sure you want to clear your entire download queue?')) {
                return;
            }

            try {
                const response = await fetch('/api/download/queue', {
                    method: 'DELETE'
                });
                
                if (!response.ok) {
                    throw new Error('Failed to clear queue');
                }

                // Clear both views
                const emptyMessage = '<div class="no-downloads">No games in your download queue</div>';
                gridContainer.innerHTML = emptyMessage;
                tableContainer.innerHTML = emptyMessage;
            } catch (error) {
                console.error('Error clearing queue:', error);
                alert('Failed to clear queue. Please try again.');
            }
        });
    }
});
</script> 