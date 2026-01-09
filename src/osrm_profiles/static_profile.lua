-- Custom OSRM profile with preference rates
-- All highways, waterways, and railways are routable
-- Specific types get custom weights from CSV, others get default weight

api_version = 4

function setup()
  return {
    properties = {
      weight_name = 'preference',
      max_speed_for_map_matching = 40,
      weight_precision = 1,
      continue_straight_at_waypoint = true,
      use_turn_restrictions = false
    }
  }
end

function process_node(profile, node, result, relations)
  -- No barrier processing needed
end

function process_way(profile, way, result, relations)
  local highway = way:get_value_by_key('highway')
  local waterway = way:get_value_by_key('waterway')
  local railway = way:get_value_by_key('railway')
  
  local rate = 0
  
  -- Check if way has any routable feature
  local is_routable = (highway and highway ~= '') or 
                      (waterway and waterway ~= '') or 
                      (railway and railway ~= '')
  
  if not is_routable then
    return  -- Not a highway, waterway, or railway - skip it
  end
  
  -- Default rate for anything not specified
  rate = 1
  
  -- Apply specific rates from your CSV for highways
  if highway == 'motorway' then
    rate = 18
  elseif highway == 'trunk' then
    rate = 15
  elseif highway == 'primary' then
    rate = 6
  elseif highway == 'secondary' then
    rate = 5
  elseif highway == 'tertiary' then
    rate = 4
  elseif highway == 'unclassified' then
    rate = 3
  elseif highway == 'residential' then
    rate = 2
  elseif highway == 'living_street' then
    rate = 1
  end
  
  -- Apply specific rates from your CSV for waterways
  if waterway == 'river' then
    rate = 20
  elseif waterway == 'stream' then
    rate = 10
  elseif waterway == 'canal' then
    rate = 10
  elseif waterway == 'drain' then
    rate = 3
  end
  
  -- Apply specific rates from your CSV for railways
  if railway == 'rail' then
    rate = 18
  elseif railway == 'disused' then
    rate = 12
  end
  
  -- Make the way routable with the assigned rate
  result.forward_mode = mode.driving
  result.backward_mode = mode.driving
  result.forward_speed = 1
  result.backward_speed = 1
  result.forward_rate = rate
  result.backward_rate = rate
end

function process_turn(profile, turn)
  -- No turn penalties
  turn.duration = 0
  turn.weight = 0
end

return {
  setup = setup,
  process_way = process_way,
  process_node = process_node,
  process_turn = process_turn
}
