#!/usr/bin/env python3
"""
Generate OSRM Lua profile from CSV specification.

Usage:
    python generate_profile.py weights.csv output_profile.lua
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path


def parse_csv(csv_path):
    """Parse CSV file and organize weights by OSM key."""
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


def generate_lua_profile(weights_by_key, all_keys, output_path):
    """Generate Lua profile file."""
    
    # Start building the Lua file
    lua_content = """-- Custom OSRM profile generated from CSV
-- All specified OSM keys are routable
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
    
    # Add the rest of the profile
    lua_content += """  -- Make the way routable with the assigned rate
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
"""
    
    # Write to file
    with open(output_path, 'w') as f:
        f.write(lua_content)
    
    print(f"✓ Generated profile: {output_path}")
    print(f"✓ Routable OSM keys: {', '.join(all_keys)}")
    print(f"✓ Total weight mappings: {sum(len(v) for v in weights_by_key.values())}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python generate_profile.py <input.csv> <output.lua>")
        print("\nExample:")
        print("  python generate_profile.py weights.csv custom_profile.lua")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    output_path = sys.argv[2]
    
    # Validate input file exists
    if not Path(csv_path).exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Parse CSV and generate profile
    try:
        weights_by_key, all_keys = parse_csv(csv_path)
        generate_lua_profile(weights_by_key, all_keys, output_path)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
