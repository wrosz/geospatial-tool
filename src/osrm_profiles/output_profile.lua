-- Custom OSRM profile for spatial partitioning
-- Designed to find logical partition lines along major roads, rivers, and railways
-- Prefers straight routes along high-value features

api_version = 4

function setup()
  return {
    properties = {
      weight_name = 'preference',
      weight_precision = 1,
      continue_straight_at_waypoint = true,
      use_turn_restrictions = false,
      u_turn_penalty = 20
    },
    
    -- Turn penalty for preferring straight partition lines
    turn_penalty = 7.5
  }
end

function process_node(profile, node, result, relations)
  -- No barrier processing needed
end

function process_way(profile, way, result, relations)
  local highway = way:get_value_by_key('highway')
  local railway = way:get_value_by_key('railway')
  local waterway = way:get_value_by_key('waterway')

  local rate = 0

  -- Check if way has any routable feature
  local is_routable = (highway and highway ~= '') or 
                      (railway and railway ~= '') or 
                      (waterway and waterway ~= '')

  if not is_routable then
    return  -- Not a routable feature - skip it
  end

  -- Default rate for anything not specified
  rate = 1

  -- Apply specific rates for highway
  if highway == 'motorway' then
    rate = 90
  elseif highway == 'motorway_link' then
    rate = 45
  elseif highway == 'trunk' then
    rate = 85
  elseif highway == 'trunk_link' then
    rate = 40
  elseif highway == 'primary' then
    rate = 65
  elseif highway == 'primary_link' then
    rate = 30
  elseif highway == 'secondary' then
    rate = 55
  elseif highway == 'secondary_link' then
    rate = 25
  elseif highway == 'tertiary' then
    rate = 40
  elseif highway == 'tertiary_link' then
    rate = 20
  elseif highway == 'unclassified' then
    rate = 25
  elseif highway == 'residential' then
    rate = 25
  elseif highway == 'living_street' then
    rate = 10
  elseif highway == 'service' then
    rate = 15
  end

  -- Apply specific rates for railway
  if railway == 'rail' then
    rate = 85
  elseif railway == 'lightrail' then
    rate = 40
  end

  -- Apply specific rates for waterway
  if waterway == 'river' then
    rate = 90
  elseif waterway == 'stream' then
    rate = 65
  elseif waterway == 'canal' then
    rate = 65
  elseif waterway == 'drain' then
    rate = 5
  end

  -- Make the way routable with the assigned rate
  result.forward_mode = mode.driving
  result.backward_mode = mode.driving
  result.forward_speed = rate
  result.backward_speed = rate
  result.forward_rate = rate
  result.backward_rate = rate
end

function process_turn(profile, turn)
  -- Apply turn penalties to prefer straight partition lines
  local turn_penalty = profile.turn_penalty

  turn.duration = 0
  turn.weight = 0

  -- Apply penalties at intersections to prefer straight routes
  if turn.number_of_roads > 2 or turn.source_mode ~= turn.target_mode or turn.is_u_turn then
    -- Simple angle-based penalty: penalty increases with turn angle
    -- 0° (straight) = 0 penalty
    -- 90° = ~half max penalty
    -- 180° (u-turn) = max penalty
    local angle_fraction = math.abs(turn.angle) / 180.0
    turn.duration = turn_penalty * angle_fraction

    -- Add extra penalty for u-turns
    if turn.is_u_turn then
      turn.duration = turn.duration + profile.properties.u_turn_penalty
    end
  end

  -- Apply turn penalties to routing weight
  turn.weight = turn.duration
end

return {
  setup = setup,
  process_way = process_way,
  process_node = process_node,
  process_turn = process_turn
}
