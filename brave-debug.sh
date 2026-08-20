#!/bin/bash
# Dedicated Brave launcher with Chrome DevTools Protocol enabled on port 9222
# Uses a separate profile to avoid interfering with your normal Brave session

open -a "Brave Browser" --args \
  --remote-debugging-port=9222 \
  --remote-allow-origins="*" \
  --user-data-dir="$HOME/BraveDebugProfile"