#!/bin/bash

# Script to generate new sites.md and update README.md
# Usage: ./update_sites.sh

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🔄 Generating new sites.md...${NC}"

# Generate new sites.md file using the scrape command
if command -v scrape &> /dev/null; then
    scrape -t sites.md
elif [ -f "./scrape.py" ]; then
    python ./scrape.py -t sites.md
else
    echo -e "${RED}❌ Error: scrape command not found. Make sure scrape.py is executable or in PATH.${NC}"
    exit 1
fi

# Check if sites.md was generated successfully
if [ ! -f "sites.md" ]; then
    echo -e "${RED}❌ Error: sites.md was not generated successfully.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ sites.md generated successfully.${NC}"

# Check if README.md exists
if [ ! -f "README.md" ]; then
    echo -e "${RED}❌ Error: README.md not found.${NC}"
    exit 1
fi

echo -e "${YELLOW}🔄 Updating README.md with new sites table...${NC}"

# Create backup of README.md
cp README.md README.md.backup
echo -e "${GREEN}✅ Backup created: README.md.backup${NC}"

# Read the sites.md content
SITES_CONTENT=$(cat sites.md)

# Use awk to replace the sites table section in README.md
awk -v sites_content="$SITES_CONTENT" '
BEGIN { 
    in_sites_section = 0
    table_started = 0
    replacement_done = 0
}

# Detect the start of the sites section
/^### Supported sites and modes:/ {
    print $0
    in_sites_section = 1
    next
}

# When in sites section, look for the table start
in_sites_section && /^\| code/ {
    if (!replacement_done) {
        print ""
        print "Refer to this table of supported sites with available modes and metadata, or see the current configuration with latest updates by simply running `scrape` without arguments."
        print ""
        print sites_content
        replacement_done = 1
        table_started = 1
    }
    next
}

# Skip lines until we find the end of the table section
in_sites_section && table_started && /^```/ {
    print $0
    in_sites_section = 0
    table_started = 0
    next
}

# Skip table content and footnotes while in table section
in_sites_section && table_started {
    next
}

# Print all other lines
!in_sites_section || !table_started {
    print $0
}
' README.md > README.md.tmp

# Replace README.md with the updated version
mv README.md.tmp README.md

echo -e "${GREEN}✅ README.md updated successfully!${NC}"

# Show summary
echo -e "\n${YELLOW}📊 Summary:${NC}"
echo -e "- Generated new sites.md"
echo -e "- Updated README.md with new sites table"
echo -e "- Created backup: README.md.backup"

# Optional: Show diff if requested
if [ "$1" = "--show-diff" ]; then
    echo -e "\n${YELLOW}📋 Changes made:${NC}"
    diff -u README.md.backup README.md || true
fi

echo -e "\n${GREEN}🎉 Update completed successfully!${NC}"
