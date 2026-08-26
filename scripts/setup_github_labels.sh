#!/usr/bin/env bash
# VectoTrace GitHub Issue Labels Setup
# Ensure you have the GitHub CLI (gh) installed and authenticated.

set -euo pipefail

echo "Creating standard issue labels for VectoTrace..."

declare -A LABELS=(
  ["phase:baseline"]="0e8a16:Phase 0 Baseline and planning controls"
  ["phase:deployment"]="1d76db:Phase 1 Production deployment"
  ["phase:quality"]="006b75:Phase 2 Quality gates"
  ["phase:probes"]="5319e7:Phase 3 Distributed probes"
  ["phase:response"]="b60205:Phase 4 On-call response"
  ["phase:slos"]="fbca04:Phase 5 SLOs and error budgets"
  ["phase:status-page"]="0052cc:Phase 6 Status-page platform"
  ["phase:subscribers"]="1d76db:Phase 7 Subscriber delivery"
  ["phase:postmortems"]="0e8a16:Phase 8 Postmortems"
  ["phase:advanced-checks"]="5319e7:Phase 9 Advanced checks"
  ["phase:security"]="d93f0b:Phase 10 Security and enterprise"
  ["phase:ecosystem"]="006b75:Phase 11 Ecosystem"
  ["area:backend"]="1d76db:Django API and Celery tasks"
  ["area:frontend"]="fbca04:Next.js dashboard and status pages"
  ["area:probe"]="5319e7:Probe agent and distributed execution"
  ["type:security"]="d93f0b:Security and vulnerabilities"
  ["type:migration"]="b60205:Database or data migration"
  ["type:operations"]="0052cc:Infrastructure and deployment"
)

for label in "${!LABELS[@]}"; do
  value="${LABELS[$label]}"
  color="${value%%:*}"
  description="${value#*:}"
  
  echo "Setting label: $label"
  # This command will fail if 'gh' is not installed, but it's meant to be run manually by operators
  gh label create "$label" --color "$color" --description "$description" --force || true
done

echo "Labels created successfully."
