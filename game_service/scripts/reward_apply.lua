--[[
  Atomic Mana Award — applies a verified RewardEvent to game state.

  Combines the cap-and-credit operation into a single indivisible step so
  two concurrent reward events for the same user cannot both pass the cap
  check and over-award (audit finding #15). Daily cap is supplied via ARGV
  rather than hardcoded so master_config.json remains the single source of
  truth (audit finding #23).

  Idempotency for the event itself is enforced upstream in
  process_reward_event via SADD-and-branch on game:processed_events
  (audit finding #9).

  KEYS[1] = game:state:{user_id}                  (hash, mana_balance field)
  KEYS[2] = game:daily_cap:{user_id}:{YYYY-MM-DD} (string counter)
  ARGV[1] = amount  (positive integer, the event's mana_award amount)
  ARGV[2] = daily_cap (positive integer, from game_config.get_daily_mana_cap)
  ARGV[3] = counter_ttl_seconds (e.g. 90000 ≈ 25h, gives sub-day buffer)

  Returns: { new_mana_balance, amount_actually_awarded }
    - amount_actually_awarded == 0 means the daily cap was already reached;
      no Mana was credited and the daily counter was not advanced.
    - amount_actually_awarded < ARGV[1] means the cap was partially hit and
      the award was clamped to (cap - current).
--]]

local state_key   = KEYS[1]
local daily_key   = KEYS[2]
local amount      = tonumber(ARGV[1])
local daily_cap   = tonumber(ARGV[2])
local ttl_seconds = tonumber(ARGV[3])

local current = tonumber(redis.call("GET", daily_key) or "0")

-- Cap already reached → no-op award. Return current balance for logging.
if current >= daily_cap then
    local balance = tonumber(redis.call("HGET", state_key, "mana_balance") or "0")
    return {balance, 0}
end

-- Clamp award to remaining headroom.
local headroom = daily_cap - current
local awarded = math.min(amount, headroom)

local new_balance = redis.call("HINCRBY", state_key, "mana_balance", awarded)
redis.call("INCRBY", daily_key, awarded)
redis.call("EXPIRE", daily_key, ttl_seconds)

return {new_balance, awarded}
