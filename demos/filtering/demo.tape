Set Shell bash
Set FontSize 22
Set Width 1920
Set Height 1080
Set Padding 0
Output demos/filtering/filtering.mp4

Hide
Type "uv run demos/filtering/generate.py --seed 42 | uv run jnav"
Enter
Sleep 2s

# Pre-seed the columns we're about to filter against (still hidden)
Type "S"
Sleep 200ms
Type "a"
Type ".path"
Enter
Type "a"
Type ".status"
Enter
Type "a"
Type ".latency_ms"
Enter
Type "a"
Type ".is_admin"
Enter
Escape
Sleep 400ms
Show
Sleep 0.5s

Type "F"
Sleep 0.5s

# Add .path at the root
Type "a"
Sleep 300ms
Type@.08 '.path == "/api/orders"'
Enter
Sleep 900ms

# Descend, add .status at the root too
Type "j"
Sleep 250ms
Type "a"
Sleep 300ms
Type@.08 ".status >= 500"
Enter
Sleep 900ms

# Descend to .status, create a group as its sibling
Type "j"
Sleep 250ms
Type "g"
Sleep 900ms

# Cut .status and paste it into the group
Type "d"
Sleep 400ms
Type "p"
Sleep 1s

# Add .latency_ms to the group
Type "a"
Sleep 300ms
Type@.08 ".latency_ms > 2000"
Enter
Sleep 1s

# Rename the group
Type "r"
Sleep 300ms
Type@.08 "slow or server error"
Enter
Sleep 1.2s

# Collapse and rename the group
Space
Sleep 1s

# Back to root, add admin exclusion
Type "k"
Sleep 200ms
Type "k"
Sleep 200ms
Type "a"
Sleep 300ms
Type@.08 ".is_admin | not"
Enter
Sleep 1.5s

# Navigate to the collapsed group and negate it as the final touch
Type "j"
Sleep 200ms
Type "j"
Sleep 200ms
Type "n"
Sleep 4s
