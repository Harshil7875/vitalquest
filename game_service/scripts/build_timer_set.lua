--[[
  Atomic Build Timer — debits Mana, validates tech-tree prereqs, and writes
  the build_complete_at timestamp in a single transaction.

  Phase 9d / fix #22: prereqs are validated inside the Lua so the tech-tree
  check + debit are atomic. Previously Python ran can_upgrade() in
  application code, then called this Lua to debit. A concurrent
  skip_build_timer call could mutate game:sanctuary:{user_id} between the
  check and the Lua execution, letting a user start an upgrade their
  sanctuary doesn't actually qualify for.

  Tech-tree prereqs come from `techtree:{building_id}:tier:{N}` hashes
  seeded by game_config.sync_to_redis() at game_service boot. Each field is
  a prereq building_id and the value is the minimum tier required.

  KEYS[1] = game:state:{user_id}                           (mana_balance)
  KEYS[2] = game:builds:{user_id}                          (build timers)
  KEYS[3] = game:sanctuary:{user_id}                       (current tiers)
  KEYS[4] = techtree:{building_id}:tier:{next_tier}        (prereq hash)
  ARGV[1] = mana_cost
  ARGV[2] = building_id
  ARGV[3] = complete_at_unix_seconds
  ARGV[4] = next_tier
  ARGV[5] = idempotency_key

  Returns new_mana_balance on success, or one of:
    DUPLICATE_REQUEST | INSUFFICIENT_PREREQ | INSUFFICIENT_MANA
--]]

local state_key      = KEYS[1]
local builds_key     = KEYS[2]
local sanctuary_key  = KEYS[3]
local techtree_key   = KEYS[4]
local cost           = tonumber(ARGV[1])
local building_id    = ARGV[2]
local complete_at    = ARGV[3]
local next_tier      = ARGV[4]
local idem_key       = ARGV[5]
local processed_key  = "game:processed_txns"

if redis.call("SISMEMBER", processed_key, idem_key) == 1 then
    return {err = "DUPLICATE_REQUEST"}
end

-- Validate tech-tree prereqs. Each (prereq_building, required_tier) pair
-- in techtree:{building_id}:tier:{next_tier} must be satisfied by the
-- player's current sanctuary state. An empty / missing techtree key is
-- treated as "no prereqs" — that's the canonical encoding for tier-1
-- builds.
local prereqs = redis.call("HGETALL", techtree_key)
for i = 1, #prereqs, 2 do
    local prereq_building = prereqs[i]
    local required_tier = tonumber(prereqs[i + 1])
    local current_tier = tonumber(redis.call("HGET", sanctuary_key, prereq_building) or "0")
    if current_tier < required_tier then
        return {err = "INSUFFICIENT_PREREQ"}
    end
end

local balance = tonumber(redis.call("HGET", state_key, "mana_balance") or "0")
if balance < cost then
    return {err = "INSUFFICIENT_MANA"}
end

-- All checks passed — atomic debit + timer write.
local new_balance = redis.call("HINCRBY", state_key, "mana_balance", -cost)
redis.call("HSET", builds_key, building_id .. ":complete_at", complete_at)
redis.call("HSET", builds_key, building_id .. ":pending_tier", next_tier)
redis.call("SADD", processed_key, idem_key)

return new_balance
