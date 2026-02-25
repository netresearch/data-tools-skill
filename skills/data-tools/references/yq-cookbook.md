# yq Cookbook

YAML manipulation patterns using Mike Farah's yq (Go implementation).

---

## GitHub Actions Workflow Editing

### Update Action Versions

```bash
# Update a specific action
yq -i '(.jobs.build.steps[] | select(.uses == "actions/checkout@v3")).uses = "actions/checkout@v4"' \
  .github/workflows/ci.yml

# Update all occurrences of an action across all workflows
for f in .github/workflows/*.yml; do
  yq -i '(.jobs[].steps[] | select(.uses | test("^actions/checkout@"))).uses = "actions/checkout@v4"' "$f"
done

# Pin action to SHA
yq -i '
  (.jobs[].steps[] | select(.uses | test("^actions/setup-node@"))).uses =
  "actions/setup-node@1234567890abcdef1234567890abcdef12345678"
' .github/workflows/ci.yml
```

### Modify Matrix Strategy

```bash
# Set matrix values
yq -i '.jobs.test.strategy.matrix.php-version = ["8.2", "8.3", "8.4"]' \
  .github/workflows/ci.yml

# Add to matrix include
yq -i '.jobs.test.strategy.matrix.include += [{"os": "ubuntu-24.04", "php": "8.4"}]' \
  .github/workflows/ci.yml

# Remove a matrix value
yq -i '.jobs.test.strategy.matrix.node-version -= ["16"]' \
  .github/workflows/ci.yml
```

### Add or Modify Steps

```bash
# Append a step
yq -i '.jobs.build.steps += [{"name": "Run linter", "run": "npm run lint"}]' \
  .github/workflows/ci.yml

# Insert step at position (before index 2)
yq -i '.jobs.build.steps |= (
  .[:2] + [{"name": "Cache", "uses": "actions/cache@v4"}] + .[2:]
)' .github/workflows/ci.yml

# Add step with multi-line run command
yq -i '.jobs.build.steps += [{
  "name": "Build and test",
  "run": "npm ci\nnpm run build\nnpm test"
}]' .github/workflows/ci.yml

# Delete a step by name
yq -i 'del(.jobs.build.steps[] | select(.name == "Old step"))' \
  .github/workflows/ci.yml
```

### Environment and Permissions

```bash
# Set workflow-level env
yq -i '.env.FORCE_COLOR = "1"' .github/workflows/ci.yml

# Set job-level permissions
yq -i '.jobs.deploy.permissions = {"contents": "read", "id-token": "write"}' \
  .github/workflows/ci.yml

# Add concurrency control
yq -i '.concurrency = {"group": "ci-${{ github.ref }}", "cancel-in-progress": true}' \
  .github/workflows/ci.yml
```

### Triggers

```bash
# Set push trigger branches
yq -i '.on.push.branches = ["main", "release/*"]' .github/workflows/ci.yml

# Add workflow_dispatch with inputs
yq -i '.on.workflow_dispatch.inputs.environment = {
  "description": "Target environment",
  "required": true,
  "default": "staging",
  "type": "choice",
  "options": ["staging", "production"]
}' .github/workflows/ci.yml

# Set scheduled trigger
yq -i '.on.schedule = [{"cron": "0 6 * * 1"}]' .github/workflows/ci.yml
```

---

## Docker-Compose Manipulation

### Service Management

```bash
# Add a new service
yq -i '.services.redis = {
  "image": "redis:7-alpine",
  "ports": ["6379:6379"],
  "volumes": ["redis-data:/data"]
}' docker-compose.yml

# Update image tag
yq -i '.services.app.image = "myapp:2.5.0"' docker-compose.yml

# Add depends_on
yq -i '.services.app.depends_on += ["redis"]' docker-compose.yml

# Remove a service
yq -i 'del(.services.legacy)' docker-compose.yml
```

### Environment Variables

```bash
# Set environment variable (map syntax)
yq -i '.services.app.environment.DATABASE_URL = "postgres://localhost/mydb"' \
  docker-compose.yml

# Add environment variable (list syntax)
yq -i '.services.app.environment += ["NEW_VAR=value"]' docker-compose.yml

# Read all environment variables for a service
yq '.services.app.environment' docker-compose.yml
```

### Volumes and Networks

```bash
# Add a named volume
yq -i '.volumes.pgdata = {"driver": "local"}' docker-compose.yml

# Add volume mount to service
yq -i '.services.db.volumes += ["pgdata:/var/lib/postgresql/data"]' docker-compose.yml

# Add custom network
yq -i '.networks.backend = {"driver": "bridge"}' docker-compose.yml
yq -i '.services.app.networks += ["backend"]' docker-compose.yml
```

---

## Kubernetes Manifest Editing

### Deployment Updates

```bash
# Update container image
yq -i '(.spec.template.spec.containers[] | select(.name == "app")).image = "myapp:3.0"' \
  deployment.yml

# Set resource limits
yq -i '(.spec.template.spec.containers[] | select(.name == "app")).resources = {
  "requests": {"memory": "256Mi", "cpu": "250m"},
  "limits": {"memory": "512Mi", "cpu": "500m"}
}' deployment.yml

# Add environment variable
yq -i '(.spec.template.spec.containers[] | select(.name == "app")).env += [{
  "name": "LOG_LEVEL",
  "value": "info"
}]' deployment.yml

# Update replicas
yq -i '.spec.replicas = 3' deployment.yml

# Add annotation
yq -i '.metadata.annotations["app.kubernetes.io/version"] = "3.0.0"' deployment.yml
```

### ConfigMap and Secret

```bash
# Update ConfigMap data
yq -i '.data["config.yaml"] = "key: new-value\nother: setting"' configmap.yml

# Add label to all resources in multi-doc
yq eval-all -i '.metadata.labels["managed-by"] = "automation"' manifests.yml
```

---

## Multi-Document YAML

### Select Specific Documents

```bash
# Select by kind
yq eval-all 'select(.kind == "Service")' k8s-all.yml

# Select by name
yq eval-all 'select(.metadata.name == "my-app")' manifests.yml

# Count documents
yq eval-all '[.] | length' manifests.yml
```

### Modify Across Documents

```bash
# Add label to all documents
yq eval-all -i '.metadata.labels["team"] = "platform"' manifests.yml

# Update image in all Deployments
yq eval-all -i '
  select(.kind == "Deployment").spec.template.spec.containers[0].image = "newimage:latest"
' manifests.yml
```

### Split and Merge

```bash
# Split multi-doc into individual files
yq eval-all -s '.kind + "-" + .metadata.name' manifests.yml

# Merge multiple files into one multi-doc
yq eval-all '.' deployment.yml service.yml configmap.yml > combined.yml
```

---

## Format Conversion

### YAML to JSON

```bash
# Single file
yq -o json config.yml

# Write to file
yq -o json config.yml > config.json

# Pretty-print JSON
yq -o json -P config.yml
```

### JSON to YAML

```bash
# Convert JSON to YAML
yq -P config.json

# Pipe from stdin
curl -s https://api.example.com/config | yq -P
```

### YAML to Properties

```bash
# Flat key=value format
yq -o props config.yml
# Output: database.host = localhost
#         database.port = 5432
```

---

## Advanced Patterns

### Variables and Environment

```bash
# Use shell variable in yq
VERSION="2.0.0"
yq -i ".version = \"${VERSION}\"" chart.yaml

# Using yq's env() function
export APP_VERSION="2.0.0"
yq -i '.image.tag = env(APP_VERSION)' values.yaml

# Using strenv() for string values
export DB_HOST="db.example.com"
yq -i '.database.host = strenv(DB_HOST)' config.yml
```

### Conditional Operations

```bash
# Update only if field exists
yq -i '(.services[] | select(has("healthcheck"))).healthcheck.interval = "30s"' \
  docker-compose.yml

# Add field only if missing
yq -i '.services.app.restart //= "unless-stopped"' docker-compose.yml
```

### Comments

```bash
# yq preserves YAML comments by default

# Add a comment before a key
yq -i '.database.host line_comment="Primary database host"' config.yml

# Read comments
yq '.database.host | line_comment' config.yml
```

### Anchors and Aliases

```bash
# yq supports YAML anchors (&) and aliases (*)
# Read with anchor expansion
yq 'explode(.)' config-with-anchors.yml
```

---

## Common Idioms

| Task | yq Expression |
|------|---------------|
| Get all keys | `.services \| keys` |
| Count items | `.items \| length` |
| Check key exists | `.services \| has("redis")` |
| Get value type | `.field \| type` |
| Merge maps | `. * {"new": "value"}` |
| Delete key | `del(.unwanted)` |
| Default value | `.field // "default"` |
| String to int | `.port \| to_number` |
| Array to comma-sep | `.items \| join(",")` |
| Read from stdin | `echo "key: value" \| yq '.key'` |
