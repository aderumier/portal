<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pixel Nostalgia</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <link rel="stylesheet" href="/assets/css/style.css">
    <style>
        /* Reset and base styles */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        html, body {
            height: 100%;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #fff;
            background: #1a1a1a;
            display: flex;
            flex-direction: column;
        }

        /* Navigation styles */
        .navbar {
            background: #2a2a2a;
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .nav-content {
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .nav-brand {
            font-size: 1.5rem;
            font-weight: bold;
            color: white;
            text-decoration: none;
        }

        .nav-links {
            display: flex;
            gap: 2rem;
            align-items: center;
        }

        .nav-link {
            color: #ddd;
            text-decoration: none;
            transition: color 0.3s ease;
        }

        .nav-link:hover {
            color: white;
        }

        /* Container styles */
        .container {
            margin: 0 auto;
            padding: 2rem;
            width: 100%;
            flex: 1 0 auto; /* This makes the container take up available space */
        }

        /* Footer styles */
        .footer {
            background: #2a2a2a;
            padding: 2rem;
            text-align: center;
            flex-shrink: 0; /* Prevents the footer from shrinking */
            width: 100%;
        }

        .footer p {
            color: #888;
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="nav-content">
            <a href="/" class="nav-brand">Pixel Nostalgia</a>
            
            <?php if (isset($_SESSION['user'])): ?>
                <!-- Search bar only for logged in users -->
                <div class="header-search">
                    <form action="/search" method="GET" class="search-form">
                        <input type="text" name="q" id="header-search-input" class="search-input" placeholder="Search games...">
                        <button type="submit" class="search-button">
                            <i class="fas fa-search"></i>
                        </button>
                    </form>
                </div>
            <?php endif; ?>
            
            <div class="nav-links">
                <a href="/systems" class="nav-link">Systems</a>
                <a href="/search" class="nav-link">Search</a>
                <?php if (isset($_SESSION['user'])): ?>
                    <a href="/downloads" class="nav-link">Downloads</a>
                    <a href="/account" class="nav-link">Account</a>
                    <a href="/logout" class="nav-link">Logout</a>
                <?php else: ?>
                    <a href="/login" class="nav-link">Login with Discord</a>
                <?php endif; ?>
            </div>
        </div>
    </nav>

    <div class="container">
        <?php if (isset($content)) echo $content; ?>
    </div>

    <footer class="footer">
        <p>&copy; <?php echo date('Y'); ?> Pixel Nostalgia. All rights reserved.</p>
    </footer>
</body>
</html> 
