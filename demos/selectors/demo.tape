Set Shell bash
Set FontSize 22
Set Width 1920
Set Height 1080
Set Padding 0
Output demos/selectors/selectors.mp4

Hide
Type "uv run demos/selectors/generate.py --seed 42 | uv run jnav"
Enter
Sleep 2s
Show
Sleep 0.5s

Type "S"
Sleep 0.5s

# Add the raw instance field (a string that contains a number)
Type "a"
Sleep 300ms
Type@.08 ".instance"
Enter
Sleep 1s

# Edit it to extract just the number
Type "e"
Sleep 400ms
Type@.08 ' | split("-")[1] | tonumber'
Enter
Sleep 1.2s

# Count elements of a list
Type "a"
Sleep 300ms
Type@.08 ".items | length"
Enter
Sleep 1.2s

# Format each item of a list with string interpolation
Type "a"
Sleep 300ms
Type@.08 '.items | map("\(.name): \(.qty)")'
Enter
Sleep 1.5s

Escape
Sleep 4s
