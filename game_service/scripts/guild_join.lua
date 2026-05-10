--[[
  Atomic Guild Join — capacity check + "already in a guild" check + roster
  insert in one block. Phase 9c / fix #21.

  The previous flow was SCARD → HGET state → SADD roster, all separate
  commands. 50 users joining a guild with 1 slot could all pass the
  SCARD check before any of them SADD'd; double-clicking "join" could
  land a single user in two guilds.

  KEYS[1] = game:state:{user_id}                (will set guild_id field)
  KEYS[2] = game:guild:{guild_id}:roster        (SET, capacity-checked)
  KEYS[3] = game:guild:{guild_id}:roles         (HASH, role → "member")
  KEYS[4] = game:last_seen                      (HASH, last activity)
  ARGV[1] = user_id                             (string)
  ARGV[2] = guild_id                            (string, written into state)
  ARGV[3] = max_capacity                        (e.g. 50)
  ARGV[4] = current_time_unix

  Returns: 1 on success.
    Or `{err = "ALREADY_IN_GUILD"}` if state.guild_id is already set.
    Or `{err = "GUILD_FULL"}` if SCARD == max_capacity.
--]]

local state_key       = KEYS[1]
local roster_key      = KEYS[2]
local roles_key       = KEYS[3]
local last_seen_key   = KEYS[4]
local user_id         = ARGV[1]
local guild_id        = ARGV[2]
local max_capacity    = tonumber(ARGV[3])
local now             = ARGV[4]

local current_guild = redis.call("HGET", state_key, "guild_id")
if current_guild and current_guild ~= "" then
    return {err = "ALREADY_IN_GUILD"}
end

local count = redis.call("SCARD", roster_key)
if count >= max_capacity then
    return {err = "GUILD_FULL"}
end

redis.call("SADD", roster_key, user_id)
redis.call("HSET", roles_key, user_id, "member")
redis.call("HSET", state_key, "guild_id", guild_id)
redis.call("HSET", last_seen_key, user_id, now)
return 1
