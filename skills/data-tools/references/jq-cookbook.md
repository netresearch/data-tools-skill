# jq Cookbook

Comprehensive patterns for JSON processing with jq.

---

## Basic Extraction

```bash
# Single field
jq '.name' package.json

# Nested field
jq '.repository.url' package.json

# Array elements
jq '.items[]' response.json

# Array element by index
jq '.items[0]' response.json

# Multiple fields
jq '{name: .name, version: .version}' package.json
```

---

## Filtering

```bash
# Select matching objects from array
jq '.users[] | select(.role == "admin")' users.json

# Multiple conditions
jq '.items[] | select(.age > 18 and .active == true)' data.json

# Null-safe access
jq '.items[] | select(.email != null)' data.json

# Regex matching
jq '.files[] | select(.name | test("^test.*\\.js$"))' manifest.json
```

---

## Transformation

```bash
# Map over array
jq '[.items[] | {id: .id, label: .name}]' data.json

# Group by field
jq 'group_by(.category) | map({key: .[0].category, count: length})' items.json

# Sort
jq 'sort_by(.date) | reverse' events.json

# Flatten nested arrays
jq '[.groups[].members[]]' org.json

# Unique values
jq '[.items[].category] | unique' data.json

# Aggregate
jq '[.items[].price] | add' cart.json
```

---

## In-Place Editing

jq does not support in-place editing natively. Use a temp file pattern:

```bash
# Safe in-place edit with temp file
jq '.version = "2.0.0"' package.json > package.json.tmp && mv package.json.tmp package.json

# Or with sponge (from moreutils)
jq '.version = "2.0.0"' package.json | sponge package.json
```

> **Note:** `sponge` requires the `moreutils` package (`apt install moreutils` / `brew install moreutils`).

---

## GitHub CLI Integration

**Always prefer the `--jq` flag over piping to jq.** It saves a process and is idiomatic.

```bash
# GOOD: --jq flag (preferred)
gh api repos/owner/repo/releases --jq '.[0].tag_name'
gh pr list --json number,title,author --jq '.[] | "\(.number)\t\(.title)\t\(.author.login)"'
gh run list --json status,conclusion --jq '.[] | select(.status == "completed")'

# BAD: piping to jq (wasteful, extra process)
gh api repos/owner/repo/releases | jq '.[0].tag_name'
```

The `--jq` flag works on both `gh api` and structured `gh` commands that support `--json`.

---

## Anti-Patterns

```bash
# BAD: Fragile, breaks on formatting changes
grep '"version"' package.json | sed 's/.*: "\(.*\)".*/\1/'

# GOOD: Correct regardless of formatting
jq -r '.version' package.json
```

```bash
# BAD: Multi-line JSON defeats grep
grep '"name"' response.json

# GOOD: Handles any structure
jq '.items[].name' response.json
```

```bash
# BAD: sed on JSON changes (breaks on nested quotes, escapes)
sed -i 's/"version": "1.0.0"/"version": "2.0.0"/' package.json

# GOOD: Structural edit
jq '.version = "2.0.0"' package.json > package.json.tmp && mv package.json.tmp package.json
```

---

## API Response Parsing

### Extract Nested Data

```bash
# Get all repository names from GitHub org
gh api orgs/myorg/repos --jq '.[].full_name'

# Get release assets download URLs
gh api repos/owner/repo/releases/latest --jq '.assets[].browser_download_url'

# Extract paginated results (GitHub API)
gh api repos/owner/repo/issues --paginate --jq '.[].title'
```

### Flatten Nested Responses

```bash
# Pull requests with review info
gh pr list --json number,title,reviews --jq '
  .[] | {
    number,
    title,
    approvals: [.reviews[] | select(.state == "APPROVED") | .author.login]
  }'
```

### Handle Nullable Fields

```bash
# Default value for missing fields
jq '.items[] | {name, email: (.email // "N/A")}' users.json

# Filter out nulls
jq '[.items[] | select(.email != null)]' users.json

# Conditional field inclusion
jq '.items[] | {name} + (if .email then {email} else {} end)' users.json
```

---

## Configuration File Manipulation

### Read and Update package.json

```bash
# Read version
jq -r '.version' package.json

# Bump patch version
jq '.version |= (split(".") | .[2] = ((.[2] | tonumber) + 1 | tostring) | join("."))' \
  package.json > package.json.tmp && mv package.json.tmp package.json

# Add a dependency
jq '.dependencies["new-package"] = "^2.0.0"' package.json > package.json.tmp \
  && mv package.json.tmp package.json

# Remove a dependency
jq 'del(.devDependencies["old-package"])' package.json > package.json.tmp \
  && mv package.json.tmp package.json

# Sort dependencies alphabetically
jq '.dependencies = (.dependencies | to_entries | sort_by(.key) | from_entries)' \
  package.json > package.json.tmp && mv package.json.tmp package.json
```

### Read and Update composer.json

```bash
# Get required PHP version
jq -r '.require.php' composer.json

# Add a requirement
jq '.require["vendor/package"] = "^3.0"' composer.json > composer.json.tmp \
  && mv composer.json.tmp composer.json

# Update autoload namespace
jq '.autoload."psr-4"["App\\"] = "src/"' composer.json > composer.json.tmp \
  && mv composer.json.tmp composer.json
```

### Read and Update tsconfig.json

```bash
# Get compiler target
jq -r '.compilerOptions.target' tsconfig.json

# Enable strict mode
jq '.compilerOptions.strict = true' tsconfig.json > tsconfig.json.tmp \
  && mv tsconfig.json.tmp tsconfig.json

# Add path alias
jq '.compilerOptions.paths["@utils/*"] = ["src/utils/*"]' tsconfig.json > tsconfig.json.tmp \
  && mv tsconfig.json.tmp tsconfig.json
```

---

## Data Transformation Recipes

### Reshape Objects

```bash
# Rename keys
jq '.items[] | {id: .identifier, label: .display_name}' data.json

# Merge objects
jq '.defaults * .overrides' config.json

# Pick specific keys
jq '.items[] | {name, email}' users.json

# Exclude specific keys
jq '.items[] | del(.password, .internal_id)' users.json
```

### Array Operations

```bash
# Flatten nested arrays
jq '[.departments[].employees[]]' org.json

# Zip two arrays
jq '[transpose[] | {key: .[0], value: .[1]}]' <<< '{"a": [["x","y"],["1","2"]]}'

# Chunk array into groups of N
jq '[range(0; length; 3) as $i | .[$i:$i+3]]' data.json

# Intersection of two arrays
jq --argjson a '["a","b","c"]' --argjson b '["b","c","d"]' \
  -n '[$a[] as $x | $b[] | select(. == $x)]'
```

### Grouping and Aggregation

```bash
# Group by field and count
jq 'group_by(.status) | map({status: .[0].status, count: length})' items.json

# Group and sum
jq 'group_by(.category) | map({
  category: .[0].category,
  total: (map(.amount) | add),
  count: length
})' transactions.json

# Pivot table style
jq 'group_by(.year) | map({
  year: .[0].year,
  quarters: group_by(.quarter) | map({
    quarter: .[0].quarter,
    revenue: (map(.revenue) | add)
  })
})' sales.json
```

### String Operations

```bash
# Split and rejoin
jq '.path | split("/") | last' data.json

# String interpolation
jq '.items[] | "Item \(.id): \(.name) (\(.status))"' data.json

# Regex capture
jq '.version | capture("(?<major>\\d+)\\.(?<minor>\\d+)\\.(?<patch>\\d+)")' package.json

# Replace in string
jq '.url | gsub("http://"; "https://")' config.json
```

---

## GitHub CLI Integration Patterns

### Pull Request Workflows

```bash
# List PRs with specific label, formatted as table
gh pr list --json number,title,author,labels --jq '
  .[] | select(.labels | map(.name) | index("bug"))
  | [.number, .author.login, .title] | @tsv'

# Get PR review status
gh pr view 42 --json reviews --jq '
  .reviews | group_by(.state) | map({state: .[0].state, count: length})'

# Find PRs by author
gh pr list --json number,title,author --jq '
  [.[] | select(.author.login == "username")] | length'
```

### Repository Analysis

```bash
# List repos with specific topic
gh api orgs/myorg/repos --paginate --jq '
  [.[] | select(.topics | index("production"))] | map(.full_name)'

# Get branch protection rules
gh api repos/owner/repo/branches/main/protection --jq '{
  required_reviews: .required_pull_request_reviews.required_approving_review_count,
  ci_required: .required_status_checks.strict,
  contexts: .required_status_checks.contexts
}'

# Repo language breakdown
gh api repos/owner/repo/languages --jq 'to_entries | sort_by(-.value) | map("\(.key): \(.value)")'
```

### Actions and Workflows

```bash
# List failed workflow runs
gh run list --json status,conclusion,name,headBranch --jq '
  [.[] | select(.conclusion == "failure")]
  | map({name, branch: .headBranch})'

# Get workflow run annotations (warnings/errors)
gh api "repos/owner/repo/check-runs/12345/annotations" --jq '
  .[] | {level: .annotation_level, message: .message, file: .path, line: .start_line}'

# Check run durations
gh run list --json databaseId,name,updatedAt,createdAt --jq '
  .[:10] | map({name, id: .databaseId})'
```

---

## Advanced Patterns

### Dynamic Key Access

```bash
# Variable key name
jq --arg key "production" '.environments[$key]' config.json

# Build object with dynamic keys
jq --arg env "staging" '{($env): .defaults}' config.json

# Iterate over all keys
jq 'to_entries[] | "\(.key) = \(.value)"' flat-config.json
```

### Conditional Logic

```bash
# If-then-else
jq '.items[] | if .score >= 90 then "A" elif .score >= 80 then "B" else "C" end' grades.json

# Conditional field
jq '.items[] | . + {tier: (if .revenue > 1000000 then "enterprise" else "standard" end)}' accounts.json

# Default value (alternative operator for null/false)
jq '.items[] | .nested.field // "default"' data.json
```

### Multi-File Operations

```bash
# Merge multiple JSON files
jq -s 'add' file1.json file2.json file3.json

# Combine into array
jq -s '.' file1.json file2.json file3.json

# Deep merge
jq -s '.[0] * .[1]' base.json override.json

# Compare two files
diff <(jq --sort-keys . a.json) <(jq --sort-keys . b.json)
```

### Output Formatting

```bash
# Compact output (no whitespace)
jq -c '.' data.json

# Raw string output (no quotes)
jq -r '.name' data.json

# Tab-separated values
jq -r '.items[] | [.id, .name, .email] | @tsv' data.json

# CSV output
jq -r '.items[] | [.id, .name, .email] | @csv' data.json

# Custom delimiter
jq -r '.items[] | [.id, .name] | join(" | ")' data.json

# Pretty-print with sorted keys
jq --sort-keys '.' data.json
```

### Streaming Large Files

```bash
# Process large files without loading entirely into memory
jq --stream 'select(.[0][-1] == "name") | .[1]' huge-file.json

# Truncate arrays for inspection
jq '.items = (.items[:5] + [{"...": "truncated"}])' large-response.json
```

---

## Common Idioms

| Task | jq Expression |
|------|---------------|
| Count items | `length` or `[.items[]] \| length` |
| Check if key exists | `has("key")` |
| Get all keys | `keys` |
| Min/max of array | `min` / `max` or `min_by(.field)` |
| Sum array | `add` |
| Unique values | `unique` |
| Reverse array | `reverse` |
| First/last | `first` / `last` |
| Map to array | `[.[] \| .field]` |
| Object to pairs | `to_entries` |
| Pairs to object | `from_entries` |
| Type check | `type` (returns "object", "array", "string", etc.) |
| Empty check | `if . == null or . == [] or . == {} then "empty" end` |
