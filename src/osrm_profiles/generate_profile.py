#!/usr/bin/env python3
"""
Generate OSRM Lua profile from CSV specification for spatial partitioning.

This profile is designed to find logical partition lines (roads, rivers, railways)
that divide regions cleanly with preference for major features and straight routes.

Usage:
    python generate_profile.py weights.csv output_profile.lua [turn_config.csv]
    
If turn_config.csv is not provided, default turn penalties will be used.
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

def parse_weights_csv(csv_path):
    """Parse weights CSV file and organize by OSM key."""
    weights_by_key = defaultdict(list)
    all_keys = set()
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            osm_key = row['osm_key'].strip()
            osm_value = row['osm_value'].strip()
            weight = row['weight'].strip()
            
            all_keys.add(osm_key)
            weights_by_key[osm_key].append((osm_value, weight))
    
    return weights_by_key, sorted(all_keys)


def parse_turn_config(csv_path):
    """Parse turn configuration CSV file."""
    config = {
        'turn_penalty': 7.5,
        'u_turn_penalty': 20
    }
    
    if not csv_path or not Path(csv_path).exists():
        return config
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            param = row['parameter'].strip()
            value = row['value'].strip()
            config[param] = float(value)
    
    return config


def generate_lua_profile(weights_by_key, all_keys, turn_config, output_path):
    """Generate Lua profile file optimized for spatial partitioning."""
    
    # Start building the Lua file
    lua_content = f"""-- Custom OSRM profile for spatial partitioning
-- Designed to find logical partition lines along major roads, rivers, and railways
-- Prefers straight routes along high-value features

api_version = 4

function setup()
  return {{
    properties = {{
      weight_name = 'preference',
      weight_precision = 1,
      continue_straight_at_waypoint = true,
      use_turn_restrictions = false,
      u_turn_penalty = {turn_config['u_turn_penalty']}
    }},
    
    -- Turn penalty for preferring straight partition lines
    turn_penalty = {turn_config['turn_penalty']}
  }}
end

function process_node(profile, node, result, relations)
  -- No barrier processing needed
end

function process_way(profile, way, result, relations)
"""
    
    # Add variable declarations for each OSM key
    for key in all_keys:
        lua_content += f"  local {key} = way:get_value_by_key('{key}')\n"
    
    lua_content += "\n  local rate = 0\n\n"
    
    # Generate routability check
    lua_content += "  -- Check if way has any routable feature\n"
    lua_content += "  local is_routable = "
    conditions = [f"({key} and {key} ~= '')" for key in all_keys]
    lua_content += " or \n                      ".join(conditions)
    lua_content += "\n\n"
    
    lua_content += """  if not is_routable then
    return  -- Not a routable feature - skip it
  end

  -- Default rate for anything not specified
  rate = 1

"""
    
    # Generate weight assignments for each key
    for key in all_keys:
        if key in weights_by_key:
            lua_content += f"  -- Apply specific rates for {key}\n"
            
            items = weights_by_key[key]
            for i, (value, weight) in enumerate(items):
                if i == 0:
                    lua_content += f"  if {key} == '{value}' then\n"
                else:
                    lua_content += f"  elseif {key} == '{value}' then\n"
                lua_content += f"    rate = {weight}\n"
            
            lua_content += "  end\n\n"
    
    # Add the rest of the profile with simplified turn penalties
    lua_content += """  -- Make the way routable with the assigned rate
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
"""
    
    # Write to file
    with open(output_path, 'w') as f:
        f.write(lua_content)
    
    print(f"✓ Generated profile: {output_path}")
    print(f"✓ Purpose: Spatial partitioning along logical boundaries")
    print(f"✓ Routable OSM keys: {', '.join(all_keys)}")
    print(f"✓ Total weight mappings: {sum(len(v) for v in weights_by_key.values())}")
    print(f"✓ Turn penalty: {turn_config['turn_penalty']} (prefers straight routes)")
    print(f"✓ U-turn penalty: {turn_config['u_turn_penalty']}")


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python generate_profile.py <weights.csv> <output.lua> [turn_config.csv]")
        print("\nExample:")
        print("  python generate_profile.py weights.csv partition_profile.lua")
        print("  python generate_profile.py weights.csv partition_profile.lua turn_config.csv")
        print("\nThis generates a profile optimized for spatial partitioning:")
        print("  - Prefers major roads, rivers, and railways")
        print("  - Prefers straight routes (configurable turn penalties)")
        print("  - No access restrictions or barriers")
        sys.exit(1)
    
    weights_csv = sys.argv[1]
    output_path = sys.argv[2]
    turn_config_csv = sys.argv[3] if len(sys.argv) == 4 else None
    
    # Validate weights file exists
    if not Path(weights_csv).exists():
        print(f"Error: Weights CSV file not found: {weights_csv}")
        sys.exit(1)
    
    # Parse CSV files and generate profile
    try:
        weights_by_key, all_keys = parse_weights_csv(weights_csv)
        turn_config = parse_turn_config(turn_config_csv)
        generate_lua_profile(weights_by_key, all_keys, turn_config, output_path)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()