<?php /* Layout is included by the RenderTrait */ ?>

<!-- Link to external CSS -->
<link rel="stylesheet" href="/assets/css/search.css">

<div class="search-header">
    <h1>Search Results</h1>
    
    <div class="view-toggle">
        <button id="grid-view" class="view-btn active" title="Grid View">
            <i class="fas fa-th-large"></i>
        </button>
        <button id="table-view" class="view-btn" title="Table View">
            <i class="fas fa-list"></i>
        </button>
    </div>
</div>

<div class="search-form-container">
    <form id="search-form" class="search-form">
        <input type="text" id="search-input" name="q" value="<?php echo htmlspecialchars($query); ?>" placeholder="Search games...">
        <button type="submit">Search</button>
    </form>
</div>

<div id="search-results-container">
    <!-- Grid View -->
    <div class="search-grid active-view">
        <div id="loading" class="loading-indicator">
            <div class="spinner"></div>
            <p>Searching for games...</p>
        </div>
    </div>

    <!-- Table View -->
    <div class="search-table">
        <table>
            <thead>
                <tr>
                    <th>Game</th>
                    <th>System</th>
                    <th>Publisher</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody></tbody>
        </table>
    </div>
</div>

<div id="load-more-container">
    <button id="load-more" class="load-more-btn">Load More Results</button>
</div>

<script>
document.addEventListener('DOMContentLoaded', () => {
    const isAuthenticated = <?php echo isset($_SESSION['user']) ? 'true' : 'false'; ?>;
    const isCreator = <?php echo (isset($_SESSION['user']) && isset($_SESSION['user']['is_creator']) && $_SESSION['user']['is_creator']) ? 'true' : 'false'; ?>;
    const searchQuery = "<?php echo htmlspecialchars($query); ?>";
    const searchGrid = document.querySelector('.search-grid');
    const tableBody = document.querySelector('.search-table tbody');
    const loadMoreBtn = document.getElementById('load-more');
    const loading = document.getElementById('loading');
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');
    
    let currentPage = 1;
    let hasMoreResults = true;
    let isLoading = false;
    let currentSearchResults = []; // Store the search results for reference
    
    // View toggle functionality
    const gridView = document.getElementById('grid-view');
    const tableView = document.getElementById('table-view');
    const gridContainer = document.querySelector('.search-grid');
    const tableContainer = document.querySelector('.search-table');

    gridView.addEventListener('click', () => {
        gridView.classList.add('active');
        tableView.classList.remove('active');
        gridContainer.classList.add('active-view');
        tableContainer.classList.remove('active-view');
        localStorage.setItem('search-view', 'grid');
    });

    tableView.addEventListener('click', () => {
        tableView.classList.add('active');
        gridView.classList.remove('active');
        tableContainer.classList.add('active-view');
        gridContainer.classList.remove('active-view');
        localStorage.setItem('search-view', 'table');
    });

    // Restore user's preferred view
    const savedView = localStorage.getItem('search-view');
    if (savedView === 'table') {
        tableView.click();
    }
    
    // Search form submission
    searchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        
        // Reset search results
        searchGrid.innerHTML = '';
        tableBody.innerHTML = '';
        currentPage = 1;
        hasMoreResults = true;
        currentSearchResults = []; // Reset the stored results
        
        // Update URL without reloading page
        const url = new URL(window.location);
        url.searchParams.set('q', searchInput.value);
        window.history.pushState({}, '', url);
        
        // Load search results
        searchGames();
    });
    
    // Load initial search results if query exists
    if (searchQuery) {
        searchGames();
    } else {
        loading.style.display = 'none';
        loadMoreBtn.style.display = 'none';
        
        const noQuery = document.createElement('div');
        noQuery.className = 'no-results-message';
        noQuery.innerHTML = '<p>Enter a search term to find games.</p>';
        searchGrid.appendChild(noQuery);
    }
    
    // Handle load more button
    loadMoreBtn.addEventListener('click', () => {
        searchGames();
    });
    
    // Set up infinite scroll
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !isLoading && hasMoreResults) {
                searchGames();
            }
        });
    }, {
        rootMargin: '200px'
    });
    
    // Observe the load more button for infinite scroll
    observer.observe(loadMoreBtn);
    
    // Function to search games
    function searchGames() {
        if (isLoading) return;
        
        isLoading = true;
        loading.style.display = 'flex';
        loadMoreBtn.disabled = true;
        
        fetch(`/api/search?q=${encodeURIComponent(searchInput.value)}&page=${currentPage}`)
            .then(response => response.json())
            .then(data => {
                console.log('Search API response:', data); // Debug API response
                loading.style.display = 'none';
                isLoading = false;
                
                if (data.results && data.results.length > 0) {
                    // Store the results
                    currentSearchResults = [...currentSearchResults, ...data.results];
                    
                    // Add results to grid and table views
                    data.results.forEach(game => {
                        searchGrid.appendChild(createGameCard(game));
                        tableBody.appendChild(createGameRow(game));
                    });
                    
                    // Check if there are more results
                    hasMoreResults = data.hasMore;
                    if (hasMoreResults) {
                        loadMoreBtn.disabled = false;
                        loadMoreBtn.style.display = 'block';
                        currentPage++;
                    } else {
                        loadMoreBtn.style.display = 'none';
                    }
                } else {
                    loadMoreBtn.style.display = 'none';
                    
                    if (currentPage === 1) {
                        const noResults = document.createElement('div');
                        noResults.className = 'no-results-message';
                        noResults.innerHTML = '<p>No games found matching your search.</p>';
                        searchGrid.appendChild(noResults);
                    }
                }
            })
            .catch(error => {
                console.error('Error searching games:', error);
                loading.style.display = 'none';
                loadMoreBtn.disabled = false;
                isLoading = false;
                
                const errorMsg = document.createElement('div');
                errorMsg.className = 'error-message';
                errorMsg.innerHTML = '<p>Failed to search games. Please try again later.</p>';
                searchGrid.appendChild(errorMsg);
            });
    }
    
    // Function to create a game card
    function createGameCard(game) {
        // Clean up the game ID and extract system if possible
        const cleanGameId = game.id.replace(/^\.\//, '');
        let systemId = game.system || '';
        
        // If no system info but game ID has extension, try to extract from extension
        if (!systemId && game.id.includes('.')) {
            const extMatch = cleanGameId.match(/\.([a-zA-Z0-9]+)$/);
            if (extMatch && extMatch[1]) {
                systemId = extMatch[1].toLowerCase();
            }
        }
        
        console.log('Creating game card with ID:', cleanGameId, 'System:', systemId);
        
        const card = document.createElement('div');
        card.className = 'game-card';
        
        // Store data attributes for easier retrieval later
        card.dataset.gameId = cleanGameId;
        card.dataset.system = systemId;
        
        card.innerHTML = `
            <div class="game-image">
                <img src="${game.image ? '/media/' + game.image : '/assets/images/no-image.png'}" alt="${game.name}" loading="lazy">
            </div>
            <div class="game-details">
                <h3 class="game-title">${game.name}</h3>
                <div class="game-meta">
                    <span class="system-tag" data-system-id="${systemId}">${game.systemName ? game.systemName : 'Unknown System'}</span>
                    ${game.publisher ? `<span class="publisher">${game.publisher}</span>` : ''}
                </div>
                ${isAuthenticated && isCreator ? `
                <button class="download-btn" data-game-id="${cleanGameId}" data-system="${systemId}">Add to Downloads</button>
                ` : ''}
            </div>
        `;
        
        // Add event listener to download button if it exists
        if (isAuthenticated && isCreator) {
            const downloadBtn = card.querySelector('.download-btn');
            downloadBtn.addEventListener('click', (e) => {
                e.preventDefault();
                console.log('Clicked download button with ID:', cleanGameId, 'System:', systemId);
                addToDownloads(cleanGameId);
            });
        }
        
        return card;
    }
    
    // Function to create a table row
    function createGameRow(game) {
        // Clean up the game ID and extract system if possible
        const cleanGameId = game.id.replace(/^\.\//, '');
        let systemId = game.system || '';
        
        // If no system info but game ID has extension, try to extract from extension
        if (!systemId && game.id.includes('.')) {
            const extMatch = cleanGameId.match(/\.([a-zA-Z0-9]+)$/);
            if (extMatch && extMatch[1]) {
                systemId = extMatch[1].toLowerCase();
            }
        }
        
        console.log('Creating game row with ID:', cleanGameId, 'System:', systemId);
        
        const row = document.createElement('tr');
        
        // Store data attributes for easier retrieval later
        row.dataset.gameId = cleanGameId;
        row.dataset.system = systemId;
        
        row.innerHTML = `
            <td class="game-info">
                <img class="table-thumbnail" src="${game.image ? '/media/' + game.image : '/assets/images/no-image.png'}" alt="${game.name}" loading="lazy">
                <span>${game.name}</span>
            </td>
            <td>${game.systemName ? game.systemName : 'Unknown'}</td>
            <td>${game.publisher || 'Unknown'}</td>
            <td>
                ${isAuthenticated && isCreator ? `
                <button class="download-btn small" data-game-id="${cleanGameId}" data-system="${systemId}">Add</button>
                ` : ''}
            </td>
        `;
        
        // Add event listener to download button if it exists
        if (isAuthenticated && isCreator) {
            const downloadBtn = row.querySelector('.download-btn');
            downloadBtn.addEventListener('click', (e) => {
                e.preventDefault();
                console.log('Clicked download button with ID:', cleanGameId, 'System:', systemId);
                addToDownloads(cleanGameId);
            });
        }
        
        return row;
    }
    
    // Function to add a game to downloads
    function addToDownloads(gameId) {
        // Debug what we received
        console.log('Original game ID:', gameId);
        
        // Always clean up the game ID by removing ./ prefix
        gameId = gameId.replace(/^\.\//, '');
        console.log('Cleaned game ID:', gameId);
        
        // Check if ID already contains a system prefix (contains a slash)
        if (gameId.includes('/')) {
            console.log('Game ID already has system prefix, using as-is:', gameId);
            sendDownloadRequest(gameId);
            return;
        }
        
        // Find the complete game object from our search results
        let foundGame = currentSearchResults.find(game => {
            // Clean up the game.id to compare consistently
            let cleanGameId = game.id.replace(/^\.\//, '');
            return cleanGameId === gameId || game.id === gameId;
        });
        console.log('Found game in results:', foundGame);
        
        // If we found the game and it has system information
        if (foundGame && foundGame.system) {
            const finalId = `${foundGame.system}/${gameId}`;
            console.log('Using system from search results:', finalId);
            sendDownloadRequest(finalId);
            return;
        }
        
        // Try to extract system from button or parent element data attributes
        const clickedButton = document.querySelector(`.download-btn[data-game-id="${gameId}"]`) || 
                              document.querySelector(`.download-btn[data-game-id="\./${gameId}"]`);
        if (clickedButton) {
            const systemFromButton = clickedButton.getAttribute('data-system');
            if (systemFromButton && systemFromButton.trim() !== '') {
                const finalId = `${systemFromButton}/${gameId}`;
                console.log('Using system from button data attribute:', finalId);
                sendDownloadRequest(finalId);
                return;
            }
            
            // Try parent element
            const parentElement = clickedButton.closest('[data-system]');
            if (parentElement) {
                const systemFromParent = parentElement.getAttribute('data-system');
                if (systemFromParent && systemFromParent.trim() !== '') {
                    const finalId = `${systemFromParent}/${gameId}`;
                    console.log('Using system from parent data attribute:', finalId);
                    sendDownloadRequest(finalId);
                    return;
                }
            }
        }
        
        // Last resort: Try to extract system from file extension
        const fileExtMatch = gameId.match(/\.([a-zA-Z0-9]+)$/);
        if (fileExtMatch && fileExtMatch[1]) {
            const systemFromExt = fileExtMatch[1].toLowerCase();
            console.log('Extracted system from file extension:', systemFromExt);
            const finalId = `${systemFromExt}/${gameId}`;
            console.log('Using system from file extension:', finalId);
            sendDownloadRequest(finalId);
            return;
        }
        
        // If we've exhausted all options, send a clear error
        console.error('Could not determine system prefix for game ID:', gameId);
        alert('Could not determine the system for this game. Please try again from the system page.');
    }
    
    // Helper function to send the actual download request
    function sendDownloadRequest(gameId) {
        console.log('Sending download request with game_id:', gameId);
        
        fetch('/api/download/queue', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ game_id: gameId })
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

<style>
/* Header styles */
.search-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
}

.search-actions {
    display: flex;
    align-items: center;
    gap: 2rem;
}

/* View toggle styles */
.view-toggle {
    display: flex;
    gap: 0.5rem;
    background: #2a2a2a;
    padding: 0.25rem;
    border-radius: 4px;
}

.view-btn {
    background: none;
    border: none;
    color: #888;
    padding: 0.5rem;
    cursor: pointer;
    border-radius: 4px;
    transition: all 0.2s;
}

.view-btn:hover {
    color: white;
    background: #3a3a3a;
}

.view-btn.active {
    color: white;
    background: #3a3a3a;
}

/* Grid view styles */
.game-grid {
    display: none;
}

.game-grid.active-view {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 2rem;
}

/* Table view styles */
.game-table {
    display: none;
}

.game-table.active-view {
    display: block;
}

.game-table table {
    width: 100%;
    border-collapse: collapse;
    background: #2a2a2a;
    border-radius: 8px;
    overflow: hidden;
}

.game-table th,
.game-table td {
    padding: 1rem;
    text-align: left;
    border-bottom: 1px solid #3a3a3a;
}

.game-table th {
    background: #3a3a3a;
    color: white;
    font-weight: 600;
}

.game-table .game-info {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.game-table .table-thumbnail {
    width: 60px;
    height: 40px;
    object-fit: cover;
    border-radius: 4px;
}

/* Responsive styles */
@media (max-width: 768px) {
    .search-header {
        flex-direction: column;
        gap: 1rem;
        text-align: center;
    }

    .search-actions {
        flex-direction: column;
        gap: 1rem;
    }

    .game-grid.active-view {
        grid-template-columns: 1fr;
    }

    .game-table {
        overflow-x: auto;
    }

    .game-table table {
        min-width: 600px;
    }
}
</style> 