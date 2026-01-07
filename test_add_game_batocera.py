#!/usr/bin/env python3
"""
Test script to add a game to Batocera via EmulationStation HTTP API.

Usage:
    python3 test_add_game_batocera.py

The script will prompt for:
    - System name (e.g., nes, snes, megadrive)
    - Game path (relative to system ROM directory, e.g., ./game.zip)
    - Game name
    - Optional metadata (description, image, etc.)
"""

import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
import sys

def prettify_xml(elem):
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

def create_gamelist_xml(games):
    """
    Create a gamelist.xml structure from a list of game dictionaries.
    
    Args:
        games: List of dicts, each containing game metadata
        
    Returns:
        XML string
    """
    root = ET.Element("gameList")
    
    for game in games:
        game_elem = ET.SubElement(root, "game")
        
        # Required: path (relative to system directory)
        if 'path' not in game:
            print(f"Warning: Game missing 'path', skipping: {game}")
            continue
            
        path_elem = ET.SubElement(game_elem, "path")
        path_elem.text = game['path']
        
        # Optional metadata fields
        optional_fields = [
            'name', 'desc', 'image', 'thumbnail', 'video', 'marquee',
            'rating', 'releasedate', 'developer', 'publisher', 'genre',
            'players', 'favorite', 'hidden', 'kidgame', 'playcount',
            'lastplayed'
        ]
        
        for field in optional_fields:
            if field in game and game[field] is not None:
                elem = ET.SubElement(game_elem, field)
                elem.text = str(game[field])
    
    # Return pretty-printed XML
    return prettify_xml(root)

def add_games_to_batocera(system_name: str, games: list, batocera_api_url: str = "http://127.0.0.1:1234"):
    """
    Add games to Batocera via EmulationStation HTTP API.
    
    Args:
        system_name: Batocera system name (e.g., 'nes', 'snes', 'megadrive')
        games: List of game dicts with metadata
        batocera_api_url: Base URL for Batocera HTTP server (default: http://127.0.0.1:1234)
    
    Returns:
        Response object from requests
    """
    # Build gamelist.xml content
    xml_content = create_gamelist_xml(games)
    
    print(f"\n=== Sending XML to Batocera ===")
    print(f"System: {system_name}")
    print(f"URL: {batocera_api_url}/addgames/{system_name}")
    print(f"\nXML Content:")
    print(xml_content)
    print("=" * 50)
    
    # Send POST request
    url = f"{batocera_api_url}/addgames/{system_name}"
    headers = {
        'Content-Type': 'application/xml'
    }
    
    try:
        response = requests.post(url, data=xml_content, headers=headers, timeout=10)
        return response
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to Batocera HTTP server at {batocera_api_url}")
        print("Make sure EmulationStation is running and the HTTP server is enabled.")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"Error: Request to {batocera_api_url} timed out")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

def main():
    """Interactive test script."""
    print("=" * 60)
    print("Batocera Add Game Test Script")
    print("=" * 60)
    
    # Get system name
    system_name = input("\nEnter system name (e.g., nes, snes, megadrive): ").strip()
    if not system_name:
        print("Error: System name is required")
        sys.exit(1)
    
    # Get game path
    game_path = input("Enter game path (relative to system ROM dir, e.g., ./game.zip or subdir/game.zip): ").strip()
    if not game_path:
        print("Error: Game path is required")
        sys.exit(1)
    
    # Get game name
    game_name = input("Enter game name: ").strip()
    if not game_name:
        game_name = "Unknown Game"
    
    # Build game dictionary
    game = {
        'path': game_path,
        'name': game_name
    }
    
    # Optional metadata
    print("\nOptional metadata (press Enter to skip):")
    
    desc = input("Description: ").strip()
    if desc:
        game['desc'] = desc
    
    image = input("Image path (relative, e.g., ./images/game.png): ").strip()
    if image:
        game['image'] = image
    
    thumbnail = input("Thumbnail path (relative): ").strip()
    if thumbnail:
        game['thumbnail'] = thumbnail
    
    developer = input("Developer: ").strip()
    if developer:
        game['developer'] = developer
    
    publisher = input("Publisher: ").strip()
    if publisher:
        game['publisher'] = publisher
    
    genre = input("Genre: ").strip()
    if genre:
        game['genre'] = genre
    
    players = input("Players (e.g., 1-2): ").strip()
    if players:
        game['players'] = players
    
    # Ask for Batocera API URL
    batocera_url = input("\nBatocera HTTP server URL (default: http://127.0.0.1:1234): ").strip()
    if not batocera_url:
        batocera_url = "http://127.0.0.1:1234"
    
    # Send request
    print(f"\nAdding game to Batocera...")
    response = add_games_to_batocera(system_name, [game], batocera_url)
    
    # Display results
    print(f"\n=== Response ===")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        print("\n✓ Success! Game added to Batocera.")
    elif response.status_code == 201:
        print("\n✓ Success! Game added. System will reload on next access.")
    elif response.status_code == 204:
        print("\n⚠ No games were added/updated (game may already exist).")
    elif response.status_code == 400:
        print("\n✗ Bad Request: Check your XML format and game path.")
    elif response.status_code == 404:
        print(f"\n✗ System '{system_name}' not found in Batocera.")
        print("Make sure the system name matches exactly (case-sensitive).")
    elif response.status_code == 403:
        print("\n✗ Forbidden: PublicWebAccess may be disabled.")
        print("Make sure you're connecting from localhost (127.0.0.1).")
    else:
        print(f"\n✗ Unexpected status code: {response.status_code}")

if __name__ == "__main__":
    main()

