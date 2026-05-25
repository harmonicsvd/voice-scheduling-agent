# ---- set once ----
#!/usr/bin/env bash
set -euo pipefail

BASE="http://127.0.0.1:8000"   # or your Render URL
KEY="2zAeiOr_V0dCuEt9oOC_9AEiM6q6OBcSCdtSSf-z6bjnNKulspvasyVe0_PyHPrf"
SUB="104659023322141767006"
DATE="2026-05-25"

post_event () {
  local id="$1" name="$2" time="$3" title="$4" duration="$5" mode="$6" city="$7" location="$8"

  payload=$(jq -n \
    --arg id "$id" \
    --arg name "$name" \
    --arg date "$DATE" \
    --arg time "$time" \
    --arg title "$title" \
    --arg duration "$duration" \
    --arg mode "$mode" \
    --arg sub "$SUB" \
    --arg city "$city" \
    --arg location "$location" \
    '
    {
      message: {
        toolCalls: [{
          id: $id,
          function: {
            arguments: {
              name: $name,
              date: $date,
              time: $time,
              title: $title,
              duration: $duration,
              meeting_mode: $mode,
              user_sub: $sub
            }
          }
        }]
      }
    }
    | if $city != "" then .message.toolCalls[0].function.arguments.city = $city else . end
    | if $location != "" then .message.toolCalls[0].function.arguments.location = $location else . end
    ')

  curl -sS -X POST "$BASE/create-event" \
    -H "Content-Type: application/json" \
    -H "X-Internal-API-Key: $KEY" \
    -d "$payload"
  echo
}


# 1) in_person + explicit city/location
post_event "tc1" "Varad" "09:00" "Site Survey Berlin" "45 min" "in_person" "Berlin" "Berlin Office"

# 2) in_person + explicit city/location
post_event "tc2" "Varad" "11:00" "Client Visit Hamburg" "30 min" "in_person" "Hamburg" "Hamburg Port"

# 3) in_person + no city + location only -> should use profile default city
post_event "tc3" "Varad" "13:00" "Factory Walkthrough" "60 min" "in_person" "" "Unknown Industrial Site"

# 4) in_person + city only (no location)
post_event "tc4" "Varad" "15:00" "Vendor Meeting Munich" "30 min" "in_person" "Munich" ""

# 5) online meeting
post_event "tc5" "Varad" "16:30" "Online Sync" "20 min" "online" "" ""

# 6) in_person + another city to diversify weather signal
post_event "tc6" "Varad" "18:00" "Evening Inspection Frankfurt" "40 min" "in_person" "Frankfurt" "Frankfurt Site"
