#!/bin/sh
# Copy the tracked voice-profile files into the Hermes data volume.
# This container is dedicated to the speaker, so its default Hermes home
# (/opt/data) is the "xiaoqi-home" profile.
# Run through: docker compose run --rm --entrypoint sh hermes /seed/profile/install.sh
set -eu

HOME_DIR=/opt/data
mkdir -p "$HOME_DIR/skills"
# Never seed Hermes' bundled skill catalog: it would bloat every voice prompt.
touch "$HOME_DIR/.no-bundled-skills"
cp /seed/profile/config.yaml "$HOME_DIR/config.yaml"
cp /seed/profile/SOUL.md "$HOME_DIR/SOUL.md"
cp -R /seed/profile/skills/. "$HOME_DIR/skills/"
# MCP servers (config.yaml mcp_servers): voice-taught scenes and linkages, and
# device history (home_history imports home_rules' HA client).
mkdir -p "$HOME_DIR/mcp"
for server in home_rules home_history; do
    rm -rf "$HOME_DIR/mcp/$server"
    cp -R "/seed/profile/mcp/$server" "$HOME_DIR/mcp/"
done
chown -R 10000:10000 "$HOME_DIR"
echo "Installed xiaoqi-home profile files into $HOME_DIR"
