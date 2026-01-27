#!/usr/bin/env bash
set -euo pipefail

# Fetch published SCT documentation HTML for offline use.
# This script is opt-in and does not affect SpinalfMRIprep pipeline steps.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default SCT image from SpinalfMRIprep's S0_setup.py
SCT_IMAGE_DEFAULT="vnmd/spinalcordtoolbox_7.2:20251215"
SCT_IMAGE="${SCT_IMAGE:-$SCT_IMAGE_DEFAULT}"

# Infer SCT version from image tag if not provided
SCT_VERSION="${SCT_VERSION:-}"
if [[ -z "$SCT_VERSION" ]]; then
    if [[ "$SCT_IMAGE" =~ spinalcordtoolbox_([0-9]+\.[0-9]+) ]]; then
        SCT_VERSION="${BASH_REMATCH[1]}"
    else
        echo "Error: Could not infer SCT_VERSION from image tag: $SCT_IMAGE" >&2
        echo "Please set SCT_VERSION explicitly (e.g., SCT_VERSION=7.2 $0)" >&2
        exit 1
    fi
fi

OUT_DIR="${OUT_DIR:-$PROJECT_ROOT/docs/vendor/sct/${SCT_VERSION}}"
SITE_DIR="${OUT_DIR}/site"
PROV="${OUT_DIR}/PROVENANCE.txt"
TMP_ZIP="${OUT_DIR}/.sct_docs.zip"

mkdir -p "$SITE_DIR"

# Try canonical ReadTheDocs htmlzip endpoints (in order of preference)
CANDIDATE_URLS=(
    "https://spinalcordtoolbox.readthedocs.io/_/downloads/en/${SCT_VERSION}/htmlzip/"
    "https://spinalcordtoolbox.com/_/downloads/en/${SCT_VERSION}/htmlzip/"
    "https://readthedocs.org/projects/spinalcordtoolbox/downloads/htmlzip/${SCT_VERSION}/"
)

echo "Fetching SCT documentation"
echo "  SCT_VERSION=$SCT_VERSION"
echo "  SCT_IMAGE=$SCT_IMAGE"
echo "  OUT_DIR=$OUT_DIR"
echo ""

# Try each URL until one succeeds
DOWNLOADED_URL=""
SHA256=""
for URL in "${CANDIDATE_URLS[@]}"; do
    echo "Trying: $URL"
    if curl -f -L -s -o "$TMP_ZIP" "$URL" 2>/dev/null; then
        if [[ -f "$TMP_ZIP" ]] && [[ -s "$TMP_ZIP" ]]; then
            DOWNLOADED_URL="$URL"
            SHA256="$(sha256sum "$TMP_ZIP" | cut -d' ' -f1)"
            echo "  Success: downloaded $(stat -f%z "$TMP_ZIP" 2>/dev/null || stat -c%s "$TMP_ZIP" 2>/dev/null) bytes"
            break
        fi
    fi
    echo "  Failed"
done

if [[ -z "$DOWNLOADED_URL" ]]; then
    echo "htmlzip not available for version ${SCT_VERSION}, trying wget mirror fallback..."
    echo ""
    
    # Fallback: use wget to mirror the published site
    MIRROR_BASE_URLS=(
        "https://spinalcordtoolbox.com/stable/en/${SCT_VERSION}/"
        "https://spinalcordtoolbox.com/en/${SCT_VERSION}/"
        "https://spinalcordtoolbox.readthedocs.io/en/${SCT_VERSION}/"
    )
    
    MIRROR_URL=""
    for BASE_URL in "${MIRROR_BASE_URLS[@]}"; do
        echo "Checking: $BASE_URL"
        HTTP_CODE=$(curl -L -s -o /dev/null -w "%{http_code}" "$BASE_URL" 2>/dev/null || echo "000")
        if [[ "$HTTP_CODE" =~ ^2[0-9]{2}$ ]]; then
            MIRROR_URL="$BASE_URL"
            echo "  Available (HTTP $HTTP_CODE), mirroring..."
            break
        else
            echo "  Not available (HTTP $HTTP_CODE)"
        fi
    done
    
    if [[ -z "$MIRROR_URL" ]]; then
        # If specific version not available, try "latest" as fallback (unless already trying latest)
        if [[ "$SCT_VERSION" != "latest" ]] && [[ "$SCT_VERSION" != "stable" ]]; then
            echo "Version ${SCT_VERSION} not available, trying 'latest' as fallback..."
            MIRROR_BASE_URLS=(
                "https://spinalcordtoolbox.com/en/latest/"
                "https://spinalcordtoolbox.readthedocs.io/en/latest/"
            )
            for BASE_URL in "${MIRROR_BASE_URLS[@]}"; do
                echo "Checking: $BASE_URL"
                HTTP_CODE=$(curl -L -s -o /dev/null -w "%{http_code}" "$BASE_URL" 2>/dev/null || echo "000")
                if [[ "$HTTP_CODE" =~ ^2[0-9]{2}$ ]]; then
                    MIRROR_URL="$BASE_URL"
                    echo "  Available (HTTP $HTTP_CODE), using 'latest' docs"
                    # Update provenance to note the fallback
                    SCT_VERSION_FALLBACK="${SCT_VERSION} (fallback: latest)"
                    break
                else
                    echo "  Not available (HTTP $HTTP_CODE)"
                fi
            done
        fi
        
        if [[ -z "$MIRROR_URL" ]]; then
            echo "Error: Could not download SCT docs htmlzip or mirror for version ${SCT_VERSION}" >&2
            echo "Tried htmlzip URLs:" >&2
            for URL in "${CANDIDATE_URLS[@]}"; do
                echo "  - $URL" >&2
            done
            echo "Tried mirror base URLs:" >&2
            for URL in "${MIRROR_BASE_URLS[@]}"; do
                echo "  - $URL" >&2
            done
            exit 1
        fi
    fi
    
    # Use wget to mirror the site
    if ! command -v wget >/dev/null 2>&1; then
        echo "Error: 'wget' command not found. Please install wget for mirror fallback." >&2
        exit 1
    fi
    
    rm -rf "$SITE_DIR"/*
    # Extract base domain for accept/reject rules
    if [[ "$MIRROR_URL" =~ https?://([^/]+) ]]; then
        DOMAIN="${BASH_REMATCH[1]}"
    else
        DOMAIN="spinalcordtoolbox.com"
    fi
    
    echo "Mirroring documentation (this may take 5-10 minutes for full site)..."
    echo "Note: Downloading all pages and resources. Progress will be shown below."
    # Use recursive download with proper options for ReadTheDocs sites
    # Accept only HTML, CSS, JS, images, and common doc formats
    # Run with timeout but allow substantial time for large sites
    # Note: Large sites may timeout, but substantial content will be available
    timeout 600 wget \
        --recursive \
        --level=8 \
        --page-requisites \
        --adjust-extension \
        --convert-links \
        --domains="$DOMAIN,spinalcordtoolbox.com,spinalcordtoolbox.readthedocs.io,readthedocs.io" \
        --span-hosts \
        --no-host-directories \
        --cut-dirs=1 \
        --accept=html,css,js,png,jpg,jpeg,gif,svg,pdf \
        --reject=zip,tar,gz \
        --wait=0.1 \
        --timeout=15 \
        --tries=2 \
        --max-redirect=5 \
        -e robots=off \
        --quiet \
        --show-progress \
        --directory-prefix="$SITE_DIR" \
        "$MIRROR_URL" 2>&1 || {
        EXIT_CODE=$?
        if [[ $EXIT_CODE -eq 124 ]]; then
            echo ""
            echo "Note: Download timed out after 10 minutes, but substantial content was downloaded." >&2
            HTML_COUNT=$(find "$SITE_DIR" -type f -name "*.html" 2>/dev/null | wc -l)
            echo "Downloaded $HTML_COUNT HTML pages. This should cover most documentation." >&2
        else
            echo ""
            echo "Note: wget completed with exit code $EXIT_CODE, but downloaded content is available." >&2
        fi
    }
    
    DOWNLOADED_URL="$MIRROR_URL (mirrored)"
    SHA256="mirrored-$(date +%s)"
    # Determine actual version used (may have fallen back to latest)
    if [[ -n "${SCT_VERSION_FALLBACK:-}" ]]; then
        ACTUAL_VERSION="latest"
    else
        ACTUAL_VERSION="$SCT_VERSION"
    fi
    
    # Find the actual site root (wget may create subdirectories)
    # Determine which version path was actually used
    MIRROR_VERSION="${ACTUAL_VERSION:-$SCT_VERSION}"
    if [[ -d "$SITE_DIR/spinalcordtoolbox.com" ]]; then
        # Try both the requested version and actual version paths
        if [[ -d "$SITE_DIR/spinalcordtoolbox.com/en/${MIRROR_VERSION}" ]]; then
            mv "$SITE_DIR/spinalcordtoolbox.com/en/${MIRROR_VERSION}"/* "$SITE_DIR/" 2>/dev/null || true
        elif [[ -d "$SITE_DIR/spinalcordtoolbox.com/en/${SCT_VERSION}" ]]; then
            mv "$SITE_DIR/spinalcordtoolbox.com/en/${SCT_VERSION}"/* "$SITE_DIR/" 2>/dev/null || true
        elif [[ -d "$SITE_DIR/spinalcordtoolbox.com/latest" ]]; then
            mv "$SITE_DIR/spinalcordtoolbox.com/latest"/* "$SITE_DIR/" 2>/dev/null || true
        fi
        rm -rf "$SITE_DIR/spinalcordtoolbox.com"
    fi
    if [[ -d "$SITE_DIR/spinalcordtoolbox.readthedocs.io" ]]; then
        if [[ -d "$SITE_DIR/spinalcordtoolbox.readthedocs.io/en/${MIRROR_VERSION}" ]]; then
            mv "$SITE_DIR/spinalcordtoolbox.readthedocs.io/en/${MIRROR_VERSION}"/* "$SITE_DIR/" 2>/dev/null || true
        elif [[ -d "$SITE_DIR/spinalcordtoolbox.readthedocs.io/en/${SCT_VERSION}" ]]; then
            mv "$SITE_DIR/spinalcordtoolbox.readthedocs.io/en/${SCT_VERSION}"/* "$SITE_DIR/" 2>/dev/null || true
        elif [[ -d "$SITE_DIR/spinalcordtoolbox.readthedocs.io/latest" ]]; then
            mv "$SITE_DIR/spinalcordtoolbox.readthedocs.io/latest"/* "$SITE_DIR/" 2>/dev/null || true
        fi
        rm -rf "$SITE_DIR/spinalcordtoolbox.readthedocs.io"
    fi
    
    # Skip zip extraction since we used wget
    SKIP_EXTRACT=true
fi

# Extract zip (if we downloaded a zip, not mirrored)
if [[ "${SKIP_EXTRACT:-false}" != "true" ]]; then
    # Extract zip (remove any existing site content first)
    rm -rf "$SITE_DIR"/*
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$TMP_ZIP" -d "$SITE_DIR"
    else
        echo "Error: 'unzip' command not found. Please install unzip." >&2
        rm -f "$TMP_ZIP"
        exit 1
    fi
    
    # Verify index.html exists
    if [[ ! -f "$SITE_DIR/index.html" ]] && [[ ! -f "$SITE_DIR/spinalcordtoolbox-${SCT_VERSION}/index.html" ]]; then
        echo "Warning: No index.html found in extracted archive" >&2
        echo "Archive contents:" >&2
        ls -la "$SITE_DIR" | head -n 20 >&2
    fi
    
    # Clean up temp zip
    rm -f "$TMP_ZIP"
fi

# Verify index.html exists (for both zip and mirror methods)
if [[ ! -f "$SITE_DIR/index.html" ]] && [[ ! -f "$SITE_DIR/spinalcordtoolbox-${SCT_VERSION}/index.html" ]]; then
    echo "Warning: No index.html found after download/mirror" >&2
    echo "Directory contents:" >&2
    ls -la "$SITE_DIR" | head -n 20 >&2
fi

# Record container digest if Docker is available (best-effort)
IMAGE_DIGEST=""
if command -v docker >/dev/null 2>&1; then
    if docker image inspect "$SCT_IMAGE" >/dev/null 2>&1; then
        IMAGE_DIGEST="$(docker image inspect "$SCT_IMAGE" --format '{{json .RepoDigests}}' 2>/dev/null | tr -d '\n' || echo "unknown")"
    fi
fi

# Determine actual version used (may have fallen back to latest)
if [[ -n "${SCT_VERSION_FALLBACK:-}" ]]; then
    ACTUAL_VERSION="latest"
else
    ACTUAL_VERSION="$SCT_VERSION"
fi

# Write provenance
cat >"$PROV" <<EOF
SCT_VERSION_REQUESTED=$SCT_VERSION
SCT_VERSION_ACTUAL=$ACTUAL_VERSION
SCT_IMAGE=$SCT_IMAGE
SCT_IMAGE_REPODIGESTS=$IMAGE_DIGEST
SCT_DOCS_URL=$DOWNLOADED_URL
SCT_DOCS_SHA256=$SHA256
FETCHED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

echo ""
echo "Done. Documentation cached to: $OUT_DIR"
HTML_COUNT=$(find "$SITE_DIR" -type f -name "*.html" 2>/dev/null | wc -l)
SIZE=$(du -sh "$SITE_DIR" 2>/dev/null | cut -f1)
echo "Downloaded: $HTML_COUNT HTML pages ($SIZE total)"
echo ""
echo "To view locally, run:"
echo "  cd $SITE_DIR && python -m http.server 8000"
echo "Then open: http://localhost:8000"
if [[ -f "$SITE_DIR/spinalcordtoolbox-${SCT_VERSION}/index.html" ]]; then
    echo "Or: http://localhost:8000/spinalcordtoolbox-${SCT_VERSION}/"
fi

