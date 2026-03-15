--[[
  Atomic Mana Debit — executed via Redis EVAL.

  Reads the current mana_balance, checks it covers the cost,
  deducts the amount, and returns the new balance — all as a
  single indivisible operation. Prevents race conditions from
  concurrent "Buy" requests.

  KEYS[1] = game:state:{user_id}  (Redis hash key)
  ARGV[1] = cost (integer)
  ARGV[2] = idempotency_key

  Returns:
    { new_balance }  on success
    { error: "INSUFFICIENT_MANA" }  if balance too low
    { error: "DUPLICATE_REQUEST" }  if idempotency_key already processed
--]]

local state_key    = KEYS[1]
local cost         = tonumber(ARGV[1])
local idem_key     = ARGV[2]
local processed_key = "game:processed_txns"

-- Idempotency check
if redis.call("SISMEMBER", processed_key, idem_key) == 1 then
    return {err = "DUPLICATE_REQUEST"}
end

-- Check balance
local balance = tonumber(redis.call("HGET", state_key, "mana_balance") or "0")
if balance < cost then
    return {err = "INSUFFICIENT_MANA"}
end

-- Deduct and record
local new_balance = redis.call("HINCRBY", state_key, "mana_balance", -cost)
redis.call("SADD", processed_key, idem_key)

return new_balance
