--[[
  Atomic Build Timer — executed via Redis EVAL.

  Deducts Mana cost and writes the upgrade_complete_at timestamp
  in a single transaction to prevent partial state (Mana deducted
  but timer never set, or timer set but Mana never deducted).

  KEYS[1] = game:state:{user_id}    (main state hash)
  KEYS[2] = game:builds:{user_id}   (build timers hash)
  ARGV[1] = mana_cost
  ARGV[2] = building_id
  ARGV[3] = complete_at_unix_seconds
  ARGV[4] = next_tier
  ARGV[5] = idempotency_key

  Returns new_mana_balance on success, error string on failure.
--]]

local state_key    = KEYS[1]
local builds_key   = KEYS[2]
local cost         = tonumber(ARGV[1])
local building_id  = ARGV[2]
local complete_at  = ARGV[3]
local next_tier    = ARGV[4]
local idem_key     = ARGV[5]
local processed_key = "game:processed_txns"

if redis.call("SISMEMBER", processed_key, idem_key) == 1 then
    return {err = "DUPLICATE_REQUEST"}
end

local balance = tonumber(redis.call("HGET", state_key, "mana_balance") or "0")
if balance < cost then
    return {err = "INSUFFICIENT_MANA"}
end

-- Deduct Mana
local new_balance = redis.call("HINCRBY", state_key, "mana_balance", -cost)
-- Write build timer
redis.call("HSET", builds_key, building_id .. ":complete_at", complete_at)
redis.call("HSET", builds_key, building_id .. ":pending_tier", next_tier)
-- Mark idempotency
redis.call("SADD", processed_key, idem_key)

return new_balance
