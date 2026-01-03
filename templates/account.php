<div class="container my-5">
    <h1>Account Settings</h1>
    
    <div class="card mb-4">
        <div class="card-header">
            <h5 class="mb-0">User Information</h5>
        </div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-2">
                    <?php if (!empty($user['avatar'])): ?>
                        <img src="https://cdn.discordapp.com/avatars/<?php echo $user['id']; ?>/<?php echo $user['avatar']; ?>.png" 
                             alt="Avatar" class="img-fluid rounded-circle mb-3">
                    <?php else: ?>
                        <div class="default-avatar rounded-circle mb-3 d-flex align-items-center justify-content-center bg-primary text-white">
                            <?php echo substr($user['username'], 0, 1); ?>
                        </div>
                    <?php endif; ?>
                </div>
                <div class="col-md-10">
                    <h3><?php echo htmlspecialchars($user['username']); ?></h3>
                    <p class="text-muted">Discord ID: <?php echo $user['id']; ?></p>
                    <div class="badges">
                        <span class="badge bg-primary">Guild Member</span>
                        <?php if ($user['is_creator']): ?>
                            <span class="badge bg-success">Creator</span>
                        <?php endif; ?>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
            <h5 class="mb-0">API Tokens</h5>
            <button class="btn btn-primary btn-sm" id="new-token-btn">Generate New Token</button>
        </div>
        <div class="card-body">
            <div class="alert alert-info">
                <p>API tokens allow you to authenticate with the Pixel Nostalgia API from external applications like the download service.</p>
                <p>Each token has full access to your account, so keep them secure!</p>
            </div>
            
            <div id="new-token-form" class="mb-4" style="display: none;">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">Generate New Token</h5>
                        <div class="mb-3">
                            <label for="token-name" class="form-label">Token Name</label>
                            <input type="text" class="form-control" id="token-name" placeholder="e.g., Download Service">
                            <div class="form-text">Choose a name to help you remember what this token is for.</div>
                        </div>
                        <button class="btn btn-success" id="generate-token-btn">Generate</button>
                        <button class="btn btn-secondary" id="cancel-token-btn">Cancel</button>
                    </div>
                </div>
            </div>
            
            <div id="new-token-display" class="mb-4" style="display: none;">
                <div class="alert alert-warning">
                    <p><strong>Your token has been generated. Copy it now, you won't be able to see it again!</strong></p>
                    <div class="input-group mb-3">
                        <input type="text" class="form-control" id="token-value" readonly>
                        <button class="btn btn-outline-secondary" type="button" id="copy-token-btn">
                            <i class="bi bi-clipboard"></i> Copy
                        </button>
                    </div>
                </div>
            </div>
            
            <?php if (empty($tokens)): ?>
                <div class="alert alert-secondary">
                    You haven't created any API tokens yet.
                </div>
            <?php else: ?>
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Preview</th>
                                <th>Created</th>
                                <th>Last Used</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            <?php foreach ($tokens as $token): ?>
                                <tr<?php echo $token['revoked'] ? ' class="table-secondary text-muted"' : ''; ?>>
                                    <td><?php echo htmlspecialchars($token['name']); ?></td>
                                    <td><?php echo htmlspecialchars($token['token_preview']); ?></td>
                                    <td><?php echo date('M j, Y', strtotime($token['created_at'])); ?></td>
                                    <td>
                                        <?php if ($token['last_used_at']): ?>
                                            <?php echo date('M j, Y', strtotime($token['last_used_at'])); ?>
                                        <?php else: ?>
                                            Never
                                        <?php endif; ?>
                                    </td>
                                    <td>
                                        <?php if ($token['revoked']): ?>
                                            <span class="badge bg-secondary">Revoked</span>
                                        <?php elseif (isset($_SESSION['api_token']) && $_SESSION['api_token'] === $token['token']): ?>
                                            <span class="badge bg-success">Current</span>
                                        <?php else: ?>
                                            <span class="badge bg-primary">Active</span>
                                        <?php endif; ?>
                                    </td>
                                    <td>
                                        <?php if (!$token['revoked']): ?>
                                            <button class="btn btn-sm btn-danger revoke-token-btn" data-token-id="<?php echo $token['id']; ?>">
                                                Revoke
                                            </button>
                                        <?php endif; ?>
                                    </td>
                                </tr>
                            <?php endforeach; ?>
                        </tbody>
                    </table>
                </div>
            <?php endif; ?>
        </div>
    </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {
    // Show/hide new token form
    document.getElementById('new-token-btn').addEventListener('click', function() {
        document.getElementById('new-token-form').style.display = 'block';
    });
    
    document.getElementById('cancel-token-btn').addEventListener('click', function() {
        document.getElementById('new-token-form').style.display = 'none';
    });
    
    // Generate token
    document.getElementById('generate-token-btn').addEventListener('click', function() {
        const tokenName = document.getElementById('token-name').value.trim();
        if (!tokenName) {
            alert('Please enter a name for your token');
            return;
        }
        
        fetch('/api/tokens', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name: tokenName }),
            credentials: 'same-origin'
        })
        .then(response => response.json())
        .then(data => {
            if (data.token) {
                // Show token and add to copy functionality
                document.getElementById('token-value').value = data.token;
                document.getElementById('new-token-display').style.display = 'block';
                document.getElementById('new-token-form').style.display = 'none';
                
                // Refresh the page after a short delay to show the new token in the table
                setTimeout(() => {
                    window.location.reload();
                }, 10000);
            } else {
                alert('Error generating token: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error generating token:', error);
            alert('Error generating token. Please try again.');
        });
    });
    
    // Copy token to clipboard
    document.getElementById('copy-token-btn').addEventListener('click', function() {
        const tokenInput = document.getElementById('token-value');
        tokenInput.select();
        document.execCommand('copy');
        alert('Token copied to clipboard!');
    });
    
    // Revoke token buttons
    document.querySelectorAll('.revoke-token-btn').forEach(button => {
        button.addEventListener('click', function() {
            const tokenId = this.getAttribute('data-token-id');
            if (confirm('Are you sure you want to revoke this token? This cannot be undone.')) {
                fetch(`/api/tokens/${tokenId}`, {
                    method: 'DELETE',
                    credentials: 'same-origin'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.location.reload();
                    } else {
                        alert('Error revoking token: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(error => {
                    console.error('Error revoking token:', error);
                    alert('Error revoking token. Please try again.');
                });
            }
        });
    });
});
</script>

<style>
.default-avatar {
    width: 100px;
    height: 100px;
    font-size: 42px;
}
</style> 