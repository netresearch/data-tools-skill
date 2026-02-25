# CSV Processing with qsv

Patterns for fast, correct CSV/TSV processing using qsv.

---

## Data Exploration Workflow

When you encounter a new CSV file, follow this sequence:

### Step 1: Inspect Structure

```bash
# Column names
qsv headers data.csv

# Row count
qsv count data.csv

# First 5 rows in table format
qsv slice data.csv --len 5 | qsv table
```

### Step 2: Profile Data

```bash
# Full statistics (min, max, mean, stddev, nullcount, etc.)
qsv stats data.csv --everything | qsv table

# Value distribution for categorical columns
qsv frequency data.csv --select category,status | qsv table

# Check for nulls/empty values
qsv stats data.csv --everything | qsv select field,nullcount | qsv search -s nullcount "[1-9]"
```

### Step 3: Sample Data

```bash
# Random sample of 100 rows
qsv sample 100 data.csv

# Last 10 rows
qsv slice data.csv --start -10

# Every Nth row
qsv sample 50 data.csv --seed 42
```

---

## Filtering and Selection

### Column Selection

```bash
# By name
qsv select name,email,phone data.csv

# By index (1-based)
qsv select 1,3,5 data.csv

# Exclude columns
qsv select '!password,secret_key' data.csv

# Range of columns
qsv select 1-5 data.csv

# Reorder columns
qsv select email,name,id data.csv
```

### Row Filtering

```bash
# Search in specific column
qsv search -s status "active" users.csv

# Regex search
qsv search -s email "@company\\.com$" contacts.csv

# Case-insensitive search
qsv search -i -s name "smith" people.csv

# Invert match (exclude rows)
qsv search -v -s status "deleted" records.csv

# Search across all columns
qsv search "error" logs.csv
```

### Combined Filtering and Selection

```bash
# Filter then select columns
qsv search -s country "Germany" customers.csv | qsv select name,email,city

# Chain multiple filters
qsv search -s status "active" users.csv \
  | qsv search -s role "admin" \
  | qsv select name,email
```

---

## Transformation

### Sorting

```bash
# Sort by column (alphabetical)
qsv sort --select name employees.csv

# Numeric sort
qsv sort --select revenue --numeric sales.csv

# Reverse sort (descending)
qsv sort --select date --reverse events.csv

# Sort by multiple columns
qsv sort --select department,name employees.csv
```

### Deduplication

```bash
# Remove exact duplicate rows
qsv dedup data.csv

# Deduplicate by specific columns
qsv dedup --select email contacts.csv

# Show only duplicates
qsv dedup --dupes-output dupes.csv data.csv
```

### Renaming Columns

```bash
# Rename headers
qsv rename 'First Name,Last Name,Email Address' data.csv

# When you know current headers
qsv headers data.csv  # Check first
qsv rename 'id,name,email' data.csv
```

### Adding Computed Columns

```bash
# Simple expression
qsv eval "total = price * quantity" orders.csv

# String concatenation
qsv eval "full_name = first_name + ' ' + last_name" people.csv

# Conditional
qsv eval "tier = if(revenue > 1000000, 'enterprise', 'standard')" accounts.csv
```

---

## Joining Datasets

### Inner Join

```bash
# Join on matching key
qsv join user_id orders.csv id users.csv
```

### Left Join

```bash
# Keep all rows from left file
qsv join --left user_id orders.csv id users.csv
```

### Join with Column Selection

```bash
# Join then select useful columns
qsv join user_id orders.csv id users.csv \
  | qsv select 'order_id,user_id,name,email,amount'
```

### Cross-Reference Datasets

```bash
# Find orders from German customers
qsv search -s country "Germany" customers.csv | qsv select id > german_ids.csv
qsv join customer_id orders.csv id german_ids.csv
```

---

## Statistical Analysis

### Summary Statistics

```bash
# Basic stats for all columns
qsv stats data.csv | qsv table

# Full statistics including cardinality, mode, quartiles
qsv stats data.csv --everything | qsv table

# Stats for specific columns
qsv stats data.csv --select revenue,quantity --everything | qsv table
```

### Frequency Analysis

```bash
# Value counts for a column
qsv frequency data.csv --select status

# Top N values
qsv frequency data.csv --select category --limit 20

# Frequency across multiple columns
qsv frequency data.csv --select 'status,category,region'

# Frequency as percentage (pipe to further processing)
qsv frequency data.csv --select status | qsv table
```

### Grouping

```bash
# Count per group
qsv frequency data.csv --select department

# For more complex aggregations, combine with sort and dedup
qsv sort --select department data.csv | qsv dedup --select department
```

---

## Large File Handling

### Performance Tips

```bash
# Index for faster repeated operations
qsv index data.csv
# Creates data.csv.idx -- subsequent operations are faster

# Count rows (instant with index)
qsv count data.csv

# Random access with index
qsv slice data.csv --start 1000000 --len 100
```

### Splitting Large Files

```bash
# Split into chunks of N rows
qsv split --size 100000 output_dir data.csv

# Split by column value
qsv partition region output_dir data.csv
```

### Sampling for Analysis

```bash
# Analyze a sample instead of full dataset
qsv sample 10000 huge-file.csv > sample.csv
qsv stats sample.csv --everything | qsv table
```

---

## Format Conversion

### TSV to CSV

```bash
# Convert tab-delimited to CSV
qsv input --delimiter '\t' data.tsv > data.csv
```

### CSV to JSON

```bash
# Each row becomes a JSON object
qsv tojsonl data.csv  # JSON Lines format (one object per line)
```

### Excel to CSV

```bash
# qsv can read Excel files directly (if compiled with feature)
qsv excel data.xlsx > data.csv
qsv excel data.xlsx --sheet "Sheet2" > sheet2.csv
```

---

## Validation and Cleaning

### Check Data Quality

```bash
# Validate CSV structure
qsv validate data.csv

# Check for inconsistent row lengths
qsv validate data.csv 2>&1

# Count empty/null fields per column
qsv stats data.csv --everything | qsv select field,nullcount | qsv table
```

### Clean Data

```bash
# Trim whitespace from all fields
qsv trim data.csv

# Fill empty cells with default
qsv fill --default "N/A" data.csv

# Remove rows with empty required fields
qsv search -s email ".+" data.csv  # Keep only rows with non-empty email
```

---

## Anti-Patterns

```bash
# BAD: awk breaks on quoted fields containing commas
awk -F',' '{print $2}' data.csv

# GOOD: Proper CSV parsing
qsv select 2 data.csv
```

```bash
# BAD: sort does not understand CSV structure
sort -t',' -k3 -n data.csv

# GOOD: CSV-aware sort
qsv sort --select 3 --numeric data.csv
```

---

## Comparison: qsv vs Alternatives

### qsv vs awk

```bash
# Task: Sum a numeric column

# awk (breaks on quoted fields with commas)
awk -F',' '{sum += $3} END {print sum}' data.csv

# qsv (correct CSV parsing, handles quoting)
qsv stats data.csv --select 3 | qsv select sum
```

### qsv vs Python pandas

```bash
# Task: Get top 10 values by revenue

# Python (requires script, slow startup, high memory)
python3 -c "
import pandas as pd
df = pd.read_csv('data.csv')
print(df.nlargest(10, 'revenue'))
"

# qsv (one-liner, instant, low memory)
qsv sort --select revenue --numeric --reverse data.csv | qsv slice --len 10 | qsv table
```

### qsv vs csvkit

```bash
# qsv is significantly faster than csvkit for large files.
# csvkit is Python-based; qsv is compiled Rust.
# For files > 100MB, qsv is typically 10-100x faster.

# Both handle CSV correctly (quoting, escaping, encoding).
# Use qsv for performance; csvkit if qsv is unavailable.
```

---

## Common Workflows

### Log Analysis

```bash
# Parse structured logs exported as CSV
qsv search -s level "ERROR" logs.csv | qsv frequency --select source | qsv table
```

### Data Pipeline

```bash
# Filter -> Transform -> Aggregate -> Export
qsv search -s status "completed" orders.csv \
  | qsv select customer_id,amount,date \
  | qsv sort --select date --reverse \
  | qsv slice --len 1000 \
  > recent_completed.csv
```

### Report Generation

```bash
# Quick summary report
echo "=== Row Count ==="
qsv count data.csv
echo "=== Column Stats ==="
qsv stats data.csv --select revenue,quantity | qsv table
echo "=== Top Categories ==="
qsv frequency data.csv --select category --limit 5 | qsv table
```
