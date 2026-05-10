--[[
  Atomic Open Chest — decrements chest count and deposits rolled items.

  Phase 9b / fix #14: the previous flow was four sequential commands
  (HGET → HINCRBY chest -1 → roll → loop HINCRBY items) with no
  idempotency_key check. A crash mid-deposit lost items; double-clicks
  caused double chest spends.

  This Lua does it atomically. The items themselves are rolled in Python
  via secrets.SystemRandom (Lua isn't a good RNG home), passed in via
  ARGV, and persisted to `chest_result:{idempotency_key}` so a retry that
  reaches Python AFTER the original Lua completed (e.g. user refreshed
  the page) returns the same items — not a fresh roll.

  KEYS[1] = game:inventory:{user_id}:chests   (rarity → count hash)
  KEYS[2] = game:inventory:{user_id}:items    (item_id → quantity hash)
  KEYS[3] = chest_result:{idempotency_key}    (string with TTL)
  ARGV[1] = chest_rarity
  ARGV[2] = idempotency_key
  ARGV[3] = result_payload_json   (the rolled items, persisted as-is)
  ARGV[4] = ttl_seconds           (e.g. 7 days)
  ARGV[5..N] = pairs of (item_id, quantity), each as two ARGV slots

  Returns: 1 (success — items granted)
    Or `{err = "DUPLICATE_REQUEST"}` if the idempotency_key was already
    consumed (caller checks chest_result key directly to decide whether
    to read the persisted result instead).
    Or `{err = "CHEST_EMPTY"}` if no chest of the given rarity is in
    inventory.
--]]

local chests_key   = KEYS[1]
local items_key    = KEYS[2]
local result_key   = KEYS[3]
local rarity       = ARGV[1]
local idem_key     = ARGV[2]
local payload      = ARGV[3]
local ttl          = tonumber(ARGV[4])
local processed_key = "game:processed_txns"

-- Idempotency atomic check.
if redis.call("SADD", processed_key, idem_key) == 0 then
    return {err = "DUPLICATE_REQUEST"}
end

-- Verify a chest of this rarity is available.
local count = tonumber(redis.call("HGET", chests_key, rarity) or "0")
if count <= 0 then
    redis.call("SREM", processed_key, idem_key)
    return {err = "CHEST_EMPTY"}
end

-- Decrement chest count and persist the result blob.
redis.call("HINCRBY", chests_key, rarity, -1)
redis.call("SET", result_key, payload, "EX", ttl)

-- Deposit each item (id, qty pairs).
for i = 5, #ARGV, 2 do
    local item_id = ARGV[i]
    local qty = tonumber(ARGV[i + 1])
    if qty and qty > 0 then
        redis.call("HINCRBY", items_key, item_id, qty)
    end
end

return 1
