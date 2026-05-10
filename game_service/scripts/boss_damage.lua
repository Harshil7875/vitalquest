--[[
  Atomic Boss Damage — applies guild_damage to a World Boss in one step.

  The previous Python had HGET → max(0, hp - damage) → HSET, with no lock
  or transaction. Two concurrent damage events both read the same HP,
  both wrote the same new value, and one event's worth of damage was lost
  (audit finding #12). This Lua does HSETNX initialization + HINCRBY
  decrement atomically and returns whether the boss was just defeated by
  THIS specific call (not whether HP <= 0, which would double-fire on
  multiple damage events after the kill).

  Boss HP comes from ARGV (sourced from game_config.get_world_boss_hp())
  so master_config.json is the single source of truth (audit finding #24).

  KEYS[1] = game:guild:{guild_id}     (hash, boss_hp_remaining field)
  ARGV[1] = damage                    (positive integer)
  ARGV[2] = initial_hp                (positive integer, from config)

  Returns: { new_hp, defeated_by_this_call }
    - defeated_by_this_call is 1 only when this specific damage event drove
      HP from > 0 to <= 0. Subsequent damage events after the kill return
      defeated_by_this_call = 0 so loot distribution doesn't re-fire.
--]]

local guild_key = KEYS[1]
local damage    = tonumber(ARGV[1])
local initial   = tonumber(ARGV[2])

-- Initialize HP atomically on first damage event of the raid week.
-- HSETNX returns 1 if the field was set (didn't exist); 0 otherwise.
redis.call("HSETNX", guild_key, "boss_hp_remaining", tostring(initial))

-- Read current HP after the optional initialization.
local current = tonumber(redis.call("HGET", guild_key, "boss_hp_remaining"))

-- Boss already defeated by a previous event — do NOT decrement further,
-- return 0/0 so the caller doesn't double-fire loot distribution.
if current <= 0 then
    return {current, 0}
end

-- Atomic decrement. HINCRBY can drive the value below zero with a large
-- damage event; that's fine — the next call sees current <= 0 and short-
-- circuits above.
local new_hp = redis.call("HINCRBY", guild_key, "boss_hp_remaining", -damage)
local defeated_by_this_call = (current > 0 and new_hp <= 0) and 1 or 0
return {new_hp, defeated_by_this_call}
