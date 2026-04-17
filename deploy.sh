#!/usr/bin/env bash
# deploy.sh — Build and deploy JHFW serverless stack via AWS SAM
# Usage:
#   ./deploy.sh            # subsequent deploys (uses samconfig.toml)
#   ./deploy.sh --guided   # first deploy (interactive, saves samconfig.toml)

set -euo pipefail

STACK_NAME="${STACK_NAME:-jhfw-serverless}"
REGION="${AWS_REGION:-ap-southeast-2}"   # change to your preferred region

# ── Preflight checks ──────────────────────────────────────────────────────────
command -v aws  >/dev/null 2>&1 || { echo "ERROR: aws CLI not found. Install from https://aws.amazon.com/cli/"; exit 1; }
command -v sam  >/dev/null 2>&1 || { echo "ERROR: sam CLI not found. Install from https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html"; exit 1; }

echo "=== JHFW Serverless Deploy ==="
echo "Stack:  $STACK_NAME"
echo "Region: $REGION"
echo ""

# ── SAM Build ─────────────────────────────────────────────────────────────────
echo "Building SAM application..."
sam build --template template.yaml

# ── SAM Deploy ────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--guided" ] || [ ! -f samconfig.toml ]; then
    echo ""
    echo "Running guided deploy (first time setup)..."
    sam deploy \
        --guided \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --capabilities CAPABILITY_IAM \
        --no-fail-on-empty-changeset
else
    echo "Deploying..."
    sam deploy \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --capabilities CAPABILITY_IAM \
        --no-fail-on-empty-changeset
fi

# ── Fetch outputs ─────────────────────────────────────────────────────────────
echo ""
echo "=== Deployment complete ==="
echo ""

API_URL=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
    --output text 2>/dev/null || echo "")

SEEDER_FN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`SeederFunctionName`].OutputValue' \
    --output text 2>/dev/null || echo "jhfw-seeder")

if [ -n "$API_URL" ]; then
    echo "API URL: $API_URL"
    echo ""
    echo "Endpoints:"
    echo "  GET $API_URL/api/health"
    echo "  GET $API_URL/api/current"
    echo "  GET $API_URL/api/history?days=180"
    echo ""
fi

# ── Seed historical data ──────────────────────────────────────────────────────
echo "=== Seed historical data (first time only) ==="
echo ""
echo "Run the seeder Lambda to backfill 6 months of history:"
echo ""
echo "  aws lambda invoke \\"
echo "    --function-name $SEEDER_FN \\"
echo "    --region $REGION \\"
echo "    --log-type Tail \\"
echo "    /tmp/seeder-output.json && cat /tmp/seeder-output.json"
echo ""
echo "The seeder skips automatically if data already exists (>= 10 snapshots)."
echo ""

# ── Amplify frontend setup ────────────────────────────────────────────────────
echo "=== AWS Amplify frontend setup ==="
echo ""
echo "1. Go to: https://console.aws.amazon.com/amplify/"
echo "2. Click 'New app' → 'Host web app'"
echo "3. Connect your Git repository (GitHub/GitLab/Bitbucket)"
echo "4. Amplify will auto-detect amplify.yml for build settings"
echo "5. Add environment variable in Amplify Console:"
echo "     BACKEND_URL = $API_URL"
echo ""
echo "The build step automatically replaces the localhost URL in index.html"
echo "with your API Gateway URL."
echo ""
