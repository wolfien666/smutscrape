#!/bin/bash

# Directory containing YAML configs
CONFIG_DIR="./configs"

# Check if the directory exists
if [ ! -d "$CONFIG_DIR" ]; then
    echo "Error: Directory '$CONFIG_DIR' does not exist."
    exit 1
fi

# Iterate through all .yaml files in the configs directory
for file in "$CONFIG_DIR"/*.yaml; do
    # Check if any files match the pattern
    if [ ! -e "$file" ]; then
        echo "No .yaml files found in '$CONFIG_DIR'."
        exit 0
    fi

    echo "Processing: $file"

    # Use sed to:
    # 1. Replace {video} with {video_id}
    # 2. Delete lines containing video_key_pattern
    # -i.bak creates a backup; works on both Linux and macOS
    sed -i.bak \
        -e 's/{video}/{video_id}/g' \
        -e '/video_key_pattern/d' \
        "$file"

    # Check if sed succeeded
    if [ $? -eq 0 ]; then
        echo "Successfully updated $file"
        # Remove the backup file since changes were successful
        rm -f "$file.bak"
    else
        echo "Error processing $file; backup preserved at $file.bak"
    fi
done

echo "All files processed."
