#!/bin/bash
#
# Cleans Wealthfolio Dev data for a fresh start.
# Works for both `pnpm tauri dev` and DMG builds (same app identifier).
#

APP_ID="com.teymz.wealthfolio.dev"
APP_SUPPORT="$HOME/Library/Application Support/$APP_ID"
CACHES="$HOME/Library/Caches/$APP_ID"
PREFS="$HOME/Library/Preferences/$APP_ID.plist"
SAVED_STATE="$HOME/Library/Saved Application State/$APP_ID.savedState"

echo "=== Wealthfolio Dev Cleanup ==="
echo ""
echo "This will delete:"
[ -d "$APP_SUPPORT" ] && echo "  • $APP_SUPPORT ($(du -sh "$APP_SUPPORT" 2>/dev/null | cut -f1))"
[ -d "$CACHES" ] && echo "  • $CACHES"
[ -f "$PREFS" ] && echo "  • $PREFS"
[ -d "$SAVED_STATE" ] && echo "  • $SAVED_STATE"

# Check for mounted DMG
MOUNTED=$(ls /Volumes/ 2>/dev/null | grep -i "wealthfolio dev")
if [ -n "$MOUNTED" ]; then
    echo ""
    echo "⚠️  Found mounted DMG volume(s):"
    echo "$MOUNTED" | while read vol; do echo "  • /Volumes/$vol"; done
    echo "   These will be ejected."
fi

echo ""
read -p "Are you sure you want to delete all Wealthfolio Dev data? [y/N] " confirm

if [[ "$confirm" != [yY] && "$confirm" != [yY][eE][sS] ]]; then
    echo "Cancelled."
    exit 0
fi

# Eject any mounted DMGs
if [ -n "$MOUNTED" ]; then
    echo "$MOUNTED" | while read vol; do
        echo "Ejecting /Volumes/$vol..."
        hdiutil detach "/Volumes/$vol" 2>/dev/null
    done
fi

# Remove data
[ -d "$APP_SUPPORT" ] && rm -rf "$APP_SUPPORT" && echo "Removed $APP_SUPPORT"
[ -d "$CACHES" ] && rm -rf "$CACHES" && echo "Removed $CACHES"
[ -f "$PREFS" ] && rm -f "$PREFS" && echo "Removed $PREFS"
[ -d "$SAVED_STATE" ] && rm -rf "$SAVED_STATE" && echo "Removed $SAVED_STATE"

echo ""
echo "✓ Cleanup complete. A fresh database will be created on next launch."
