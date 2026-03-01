#!/bin/bash
# fal_image.sh — Generate image via FAL.AI and save to file
# Usage: fal_image.sh "prompt text" /path/to/output.jpg [landscape_4_3|square|portrait_4_3]
#
# Returns: 0 on success, 1 on failure
# Prints: path to saved file on success

PROMPT="$1"
OUTPUT="$2"
SIZE="${3:-landscape_4_3}"  # landscape_4_3 | square | portrait_4_3 | landscape_16_9

FAL_KEY="25a2978d-8035-4d79-a8ee-cb270b3ae319:d5e4da9d06199a417e833874867d2010"

if [ -z "$PROMPT" ] || [ -z "$OUTPUT" ]; then
  echo "Usage: fal_image.sh \"prompt\" /path/output.jpg [size]" >&2
  exit 1
fi

RESULT=$(curl -s -X POST "https://fal.run/fal-ai/flux/schnell" \
  -H "Authorization: Key $FAL_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": $(echo "$PROMPT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))'), \"image_size\": \"$SIZE\", \"num_images\": 1}")

IMG_URL=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['images'][0]['url'])" 2>/dev/null)

if [ -z "$IMG_URL" ]; then
  echo "FAL.AI error: $RESULT" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
curl -s -L "$IMG_URL" -o "$OUTPUT"

if [ $? -eq 0 ] && [ -s "$OUTPUT" ]; then
  echo "$OUTPUT"
else
  echo "Failed to download image from $IMG_URL" >&2
  exit 1
fi
