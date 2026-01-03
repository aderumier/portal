<?php /* Layout is included by the RenderTrait */ ?>

<!-- Link to external CSS -->
<link rel="stylesheet" href="/assets/css/system.css">

<div class="system-header">
    <h1><?php echo htmlspecialchars($system['name']); ?></h1>
    
    <div class="view-toggle">
        <button id="grid-view" class="view-btn active" title="Grid View">
            <i class="fas fa-th-large"></i>
        </button>
        <button id="table-view" class="view-btn" title="Table View">
            <i class="fas fa-list"></i>
        </button>
    </div>
</div>

<div class="filter-container">
    <div class="filter-input-group">
        <input type="text" id="game-filter" placeholder="Filter games..." value="<?php echo htmlspecialchars($searchQuery ?? ''); ?>">
        <button id="clear-filter" title="Clear filter"><i class="fas fa-times"></i></button>
    </div>
</div>

<div id="games-container">
    <!-- Grid View -->
    <div class="games-grid active-view">
        <div id="loading" class="loading-indicator">
            <div class="spinner"></div>
            <p>Loading games...</p>
        </div>
    </div>

    <!-- Table View -->
    <div class="games-table">
        <table>
            <thead>
                <tr>
                    <th>Game</th>
                    <th>Publisher</th>
                    <th>Year</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody></tbody>
        </table>
    </div>
</div>

<div id="load-more-container">
    <button id="load-more" class="load-more-btn">Load More Games</button>
</div>

<script>
document.addEventListener('DOMContentLoaded', () => {
    const isAuthenticated = <?php echo isset($_SESSION['user']) ? 'true' : 'false'; ?>;
    const isCreator = <?php echo (isset($_SESSION['user']) && isset($_SESSION['user']['is_creator']) && $_SESSION['user']['is_creator']) ? 'true' : 'false'; ?>;
    const systemId = "<?php echo htmlspecialchars($system['id']); ?>";
    const gameGrid = document.querySelector('.games-grid');
    const tableBody = document.querySelector('.games-table tbody');
    const loadMoreBtn = document.getElementById('load-more');
    const loading = document.getElementById('loading');
    const filterInput = document.getElementById('game-filter');
    const clearFilterBtn = document.getElementById('clear-filter');
    
    let currentPage = 1;
    let hasMoreGames = true;
    let isLoading = false;
    let allLoadedGames = []; // Store all loaded games for filtering
    
    // View toggle functionality
    const gridView = document.getElementById('grid-view');
    const tableView = document.getElementById('table-view');
    const gridContainer = document.querySelector('.games-grid');
    const tableContainer = document.querySelector('.games-table');

    gridView.addEventListener('click', () => {
        gridView.classList.add('active');
        tableView.classList.remove('active');
        gridContainer.classList.add('active-view');
        tableContainer.classList.remove('active-view');
        localStorage.setItem('view-mode', 'grid');
    });

    tableView.addEventListener('click', () => {
        tableView.classList.add('active');
        gridView.classList.remove('active');
        tableContainer.classList.add('active-view');
        gridContainer.classList.remove('active-view');
        localStorage.setItem('view-mode', 'table');
    });

    // Restore user's preferred view
    const savedView = localStorage.getItem('view-mode');
    if (savedView === 'table') {
        tableView.click();
    }
    
    // Filter functionality
    filterInput.addEventListener('input', debounce(filterGames, 300));
    
    clearFilterBtn.addEventListener('click', () => {
        filterInput.value = '';
        filterGames();
        
        // Update URL without the search parameter
        const url = new URL(window.location);
        url.searchParams.delete('search');
        window.history.pushState({}, '', url);
    });
    
    function filterGames() {
        const filterText = filterInput.value.toLowerCase().trim();
        
        // Update URL with the search parameter
        if (filterText) {
            const url = new URL(window.location);
            url.searchParams.set('search', filterText);
            window.history.pushState({}, '', url);
        }
        
        // Clear current display
        gameGrid.innerHTML = '';
        tableBody.innerHTML = '';
        
        if (!filterText) {
            // If no filter, show all loaded games
            allLoadedGames.forEach(game => {
                gameGrid.appendChild(createGameCard(game));
                tableBody.appendChild(createGameRow(game));
            });
            
            // Show load more button if there are more games to load
            if (hasMoreGames) {
                loadMoreBtn.style.display = 'block';
                loadMoreBtn.disabled = false;
            } else {
                loadMoreBtn.style.display = 'none';
            }
            return;
        }
        
        // Filter the loaded games
        const filteredGames = allLoadedGames.filter(game => 
            game.name.toLowerCase().includes(filterText) ||
            (game.publisher && game.publisher.toLowerCase().includes(filterText))
        );
        
        if (filteredGames.length > 0) {
            // Show filtered games
            filteredGames.forEach(game => {
                gameGrid.appendChild(createGameCard(game));
                tableBody.appendChild(createGameRow(game));
            });
            
            // Hide load more button when filtering
            loadMoreBtn.style.display = 'none';
        } else {
            // No matches found
            const noGames = document.createElement('div');
            noGames.className = 'no-games-message';
            noGames.innerHTML = '<p>No games found matching your filter.</p>';
            gameGrid.appendChild(noGames);
            loadMoreBtn.style.display = 'none';
        }
    }
    
    // Debounce function to limit how often filtering runs
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    // Load initial set of games
    loadGames();
    
    // Handle load more button
    loadMoreBtn.addEventListener('click', () => {
        loadGames();
    });
    
    // Set up infinite scroll
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !isLoading && hasMoreGames) {
                loadGames();
            }
        });
    }, {
        rootMargin: '200px'
    });
    
    // Observe the load more button for infinite scroll
    observer.observe(loadMoreBtn);
    
    // Function to load games
    function loadGames() {
        if (isLoading) return;
        
        isLoading = true;
        loading.style.display = 'flex';
        loadMoreBtn.disabled = true;
        
        // Add search parameter to API call if filter is active
        const filterText = filterInput.value.toLowerCase().trim();
        let apiUrl = `/api/games/${systemId}?page=${currentPage}`;
        if (filterText) {
            apiUrl += `&search=${encodeURIComponent(filterText)}`;
        }
        
        fetch(apiUrl)
            .then(response => response.json())
            .then(data => {
                loading.style.display = 'none';
                isLoading = false;
                
                if (data.games && data.games.length > 0) {
                    // Add games to allLoadedGames array for filtering
                    allLoadedGames = [...allLoadedGames, ...data.games];
                    
                    // Only display if no filter is active
                    const filterText = filterInput.value.toLowerCase().trim();
                    if (!filterText) {
                        // Add games to grid view
                        data.games.forEach(game => {
                            gameGrid.appendChild(createGameCard(game));
                            tableBody.appendChild(createGameRow(game));
                        });
                    } else {
                        // If filter is active, reapply filter to show matching games
                        filterGames();
                    }
                    
                    // Check if there are more games
                    hasMoreGames = data.hasMore;
                    if (hasMoreGames) {
                        loadMoreBtn.disabled = false;
                        currentPage++;
                    } else {
                        loadMoreBtn.style.display = 'none';
                    }
                } else {
                    loadMoreBtn.style.display = 'none';
                    
                    if (currentPage === 1) {
                        const noGames = document.createElement('div');
                        noGames.className = 'no-games-message';
                        noGames.innerHTML = '<p>No games found for this system.</p>';
                        gameGrid.appendChild(noGames);
                    }
                }
            })
            .catch(error => {
                console.error('Error loading games:', error);
                loading.style.display = 'none';
                loadMoreBtn.disabled = false;
                isLoading = false;
                
                const errorMsg = document.createElement('div');
                errorMsg.className = 'error-message';
                errorMsg.innerHTML = '<p>Failed to load games. Please try again later.</p>';
                gameGrid.appendChild(errorMsg);
            });
    }
    
    // Function to create a game card
    function createGameCard(game) {
        const card = document.createElement('div');
        card.className = 'game-card';
        
        let imageUrl = game.image ? '/media/' + game.image : '/assets/images/no-image.png';
        
        // Create card content
        card.innerHTML = `
            <div class="game-image">
                <img src="${imageUrl}" alt="${game.name}" loading="lazy">
            </div>
            <div class="game-details">
                <h3 class="game-title">${game.name}</h3>
                <div class="game-meta">
                    <span class="system-tag">${"<?php echo htmlspecialchars($system['name']); ?>"}</span>
                    ${game.publisher ? `<span class="publisher">${game.publisher}</span>` : ''}
                    ${game.year ? `<span class="year">${game.year}</span>` : ''}
                </div>
                ${isAuthenticated && isCreator ? `
                <button class="download-btn" data-game-id="${game.id}">Add to Downloads</button>
                ` : ''}
            </div>
        `;
        
        // Add event listener to download button if it exists
        if (isAuthenticated && isCreator) {
            const downloadBtn = card.querySelector('.download-btn');
            downloadBtn.addEventListener('click', (e) => {
                e.preventDefault();
                addToDownloads(game.id);
            });
        }
        
        return card;
    }
    
    // Function to create a table row
    function createGameRow(game) {
        const row = document.createElement('tr');
        
        // Create row content
        row.innerHTML = `
            <td class="game-info">
                <img class="table-thumbnail" src="${game.image ? '/media/' + game.image : '/assets/images/no-image.png'}" alt="${game.name}" loading="lazy">
                <span>${game.name}</span>
            </td>
            <td>${game.publisher || 'Unknown'}</td>
            <td>${game.year || 'Unknown'}</td>
            <td>
                ${isAuthenticated && isCreator ? `
                <button class="download-btn small" data-game-id="${game.id}">Add</button>
                ` : ''}
            </td>
        `;
        
        // Add event listener to download button if it exists
        if (isAuthenticated && isCreator) {
            const downloadBtn = row.querySelector('.download-btn');
            downloadBtn.addEventListener('click', (e) => {
                e.preventDefault();
                addToDownloads(game.id);
            });
        }
        
        return row;
    }
    
    // Function to add a game to downloads
    function addToDownloads(gameId) {
        // Clean up the game ID by removing ./ prefix if it exists
        gameId = gameId.replace(/^\.\//, '');
        
        // Add system ID to the game ID
        const fullGameId = `${systemId}/${gameId}`;
        
        console.log('Adding to downloads:', { gameId, fullGameId, systemId });
        
        fetch('/api/download/queue', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ game_id: fullGameId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Failed to add game to downloads:', data.error);
                alert('Failed to add game to downloads: ' + data.error);
            } else {
                console.log('Successfully added to downloads:', data);
                alert('Game added to downloads successfully!');
            }
        })
        .catch(error => {
            console.error('Error adding to downloads:', error);
            alert('Failed to add game to downloads. Please try again.');
        });
    }
});
</script> 