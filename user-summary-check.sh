BASE="http://127.0.0.1:8000"
KEY="2zAeiOr_V0dCuEt9oOC_9AEiM6q6OBcSCdtSSf-z6bjnNKulspvasyVe0_PyHPrf"
SUB="104659023322141767006"
DATE="2026-04-26"

curl -sS -X POST "$BASE/meetings-weather-summary" \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: $KEY" \
  -d '{
    "message": {
      "toolCalls": [{
        "id": "tc-summary",
        "function": {
          "arguments": {
            "user_sub": "'"$SUB"'",
            "date": "'"$DATE"'",
            "timezone": "Europe/Berlin"
          }
        }
      }]
    }
  }' | jq
