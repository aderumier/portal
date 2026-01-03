<?php

namespace App\Traits;

trait RenderTrait
{
    protected function render(string $template, array $data = []): string
    {
        // Add authentication status to data
        $data['isAuthenticated'] = isset($_SESSION['user']);
        
        // Extract data to make it available in the template
        extract($data);
        
        // Start output buffering for the template content
        ob_start();
        
        // Include the template
        include __DIR__ . '/../../templates/' . $template;
        
        // Get the content and clean the buffer
        $content = ob_get_clean();
        
        // Start output buffering for the final layout
        ob_start();
        
        // Include the layout with the content variable set
        include __DIR__ . '/../../templates/layout.php';
        
        // Return the final rendered page
        return ob_get_clean();
    }
} 