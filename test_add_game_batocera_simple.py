#!/usr/bin/env python3
"""
Simple non-interactive test script to add a game to Batocera.

Usage:
    python3 test_add_game_batocera_simple.py

Edit the variables at the top of the script to customize the test.
"""

import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ===== CONFIGURATION =====
BATOCERA_URL = "http://batocera:1234"
SYSTEM_NAME = "bbc"  # Change this to your system name

# Game to add
GAME = {
    'path': './Abyss (Europe).ssd',  # Relative path to game file
    'name': 'Abyss (Europe)',
    'desc': 'blabla',
    'developer': 'Test Developer',
    'publisher': 'Test Publisher',
    'genre': 'Action',
    'players': '1',
    'marquee': './media/marquee/Abyss (Europe).png'
}
# ==========================

def prettify_xml(elem):
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

def create_gamelist_xml(games):
    """Create a gamelist.xml structure from a list of game dictionaries."""
    root = ET.Element("gameList")
    
    for game in games:
        game_elem = ET.SubElement(root, "game")
        
        if 'path' not in game:
            print(f"Warning: Game missing 'path', skipping: {game}")
            continue
            
        path_elem = ET.SubElement(game_elem, "path")
        path_elem.text = game['path']
        
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
    
    return prettify_xml(root)

def main():
    print("=" * 60)
    print("Batocera Add Game Test (Simple)")
    print("=" * 60)
    print(f"System: {SYSTEM_NAME}")
    print(f"Game: {GAME['name']}")
    print(f"Path: {GAME['path']}")
    print()
    
    # Create XML
    xml_content = create_gamelist_xml([GAME])
    
    print("XML to send:")
    print("-" * 60)
    print(xml_content)
    print("-" * 60)
    print()
    
    # Send request
    url = f"{BATOCERA_URL}/addgames/{SYSTEM_NAME}"
    headers = {'Content-Type': 'application/xml'}
    
    try:
        print(f"Sending POST request to: {url}")
        response = requests.post(url, data=xml_content, headers=headers, timeout=10)
        
        print(f"\nStatus Code: {response.status_code}")
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
            print(f"\n✗ System '{SYSTEM_NAME}' not found in Batocera.")
        elif response.status_code == 403:
            print("\n✗ Forbidden: PublicWebAccess may be disabled.")
        else:
            print(f"\n✗ Unexpected status code: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print(f"\n✗ Error: Could not connect to Batocera HTTP server at {BATOCERA_URL}")
        print("Make sure EmulationStation is running and the HTTP server is enabled.")
    except requests.exceptions.Timeout:
        print(f"\n✗ Error: Request to {BATOCERA_URL} timed out")
    except Exception as e:
        print(f"\n✗ Error: {e}")

if __name__ == "__main__":
    main()

