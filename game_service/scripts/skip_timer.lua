--[[
  Atomic Skip-Timer — finalizes a building upgrade in exchange for Astral Gems.

  The previous Python did four sequential commands:
    HINCRBY astral_gems → HDEL build:complete_at → HSET sanctuary tier
    → HDEL build:pending_tier
  Concurrent skip clicks could double-charge gems, and a crash mid-sequence
  left state corrupted (gems gone but tier not promoted, or tier promoted
  but timer not cleared blocking the next upgrade). The idempotency_key
  parameter was accepted but never checked.

  This Lua does it atomically with idempotency:
    - Idempotency check via SADD on game:processed_txns (audit finding #13)
    - Gem balance check
    - Atomic gem debit + tier promote + timer clear

  KEYS[1] = game:state:{user_id}      (mana_balance, astral_gems hash)
  KEYS[2] = game:builds:{user_id}     (build timer hash)
  KEYS[3] = game:sanctuary:{user_id}  (tier hash)
  ARGV[1] = building_id
  ARGV[2] = gem_cost
  ARGV[3] = next_tier
  ARGV[4] = idempotency_key

  Returns: { new_gem_balance, new_tier }
    Or `{err = "DUPLICATE_REQUEST"}` on retry.
    Or `{err = "INSUFFICIENT_GEMS"}` if balance < cost.
    Or `{err = "TIMER_NOT_ACTIVE"}` if no build timer is in progress.
--]]

local state_key      = KEYS[1]
local builds_key     = KEYS[2]
local sanctuary_key  = KEYS[3]
local building_id    = ARGV[1]
local gem_cost       = tonumber(ARGV[2])
local next_tier      = tonumber(ARGV[3])
local idem_key       = ARGV[4]
local processed_key  = "game:processed_txns"

-- Idempotency: SADD returns 0 if already a member.
if redis.call("SADD", processed_key, idem_key) == 0 then
    return {err = "DUPLICATE_REQUEST"}
end

-- Verify a timer is actually in progress for this building.
local complete_at_field = building_id .. ":complete_at"
local pending_tier_field = building_id .. ":pending_tier"
if redis.call("HEXISTS", builds_key, complete_at_field) == 0 then
    -- Roll back the idempotency SADD so a corrected retry can succeed.
    redis.call("SREM", processed_key, idem_key)
    return {err = "TIMER_NOT_ACTIVE"}
end

-- Verify gem balance.
local balance = tonumber(redis.call("HGET", state_key, "astral_gems") or "0")
if balance < gem_cost then
    redis.call("SREM", processed_key, idem_key)
    return {err = "INSUFFICIENT_GEMS"}
end

-- Atomic gem debit + tier promote + timer clear.
local new_balance = redis.call("HINCRBY", state_key, "astral_gems", -gem_cost)
redis.call("HSET", sanctuary_key, building_id, tostring(next_tier))
redis.call("HDEL", builds_key, complete_at_field, pending_tier_field)

return {new_balance, next_tier}
