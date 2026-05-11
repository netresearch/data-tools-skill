# mlr Cookbook

Name-indexed record processing across CSV, TSV, JSON, JSON Lines, PPRINT, XTAB, and NIDX using Miller (mlr).

---

## Basic Usage

mlr reads a stream of records, applies a chain of verbs (`cat`, `filter`, `put`, `cut`, `sort`, `stats1`, `join`, ...), then writes them out. Input and output formats are independent.

```bash
# Pretty-print a CSV
mlr --csv --opprint cat data.csv

# First N records
mlr --csv head -n 5 data.csv

# Tail
mlr --csv tail -n 5 data.csv

# List column names
mlr --csv --headerless-csv-output cat data.csv | head -1
mlr --c2j cat data.csv | jq 'keys'   # via JSON
```

---

## Format Conversion

mlr's shorthand flags pair input and output formats: `--c2j` = CSV in, JSON out. The long form is `--icsv --ojson`.

```bash
# CSV <-> JSON / JSONL / TSV / Pretty-Print
mlr --c2j cat data.csv               # CSV  -> JSON array
mlr --c2l cat data.csv               # CSV  -> JSON Lines
mlr --c2t cat data.csv               # CSV  -> TSV
mlr --c2p cat data.csv               # CSV  -> PPRINT (aligned table)
mlr --j2c cat data.json              # JSON -> CSV
mlr --l2c cat events.jsonl           # JSONL -> CSV

# Long-form when shorthand doesn't cover the pair
mlr --ijsonl --oxtab cat events.jsonl
mlr --inidx --ifs comma --ojson cat raw.txt
```

---

## DSL Filtering and Transformation

`put` adds/updates fields; `filter` keeps matching records. Both use the same DSL (`$field` references, types, regex, control flow).

```bash
# Filter rows
mlr --csv filter '$status == "active" && $amount > 100' txns.csv

# Compute a new column
mlr --csv put '$total = $qty * $price' orders.csv

# Conditional assignment
mlr --csv put '$tier = $revenue > 1e6 ? "enterprise" : "standard"' accounts.csv

# Regex
mlr --csv filter '$email =~ "@example\\.com$"' users.csv

# Chained verbs with `then`
mlr --csv filter '$status == "active"' then cut -f name,email then sort -f name users.csv

# Rename / reorder fields
mlr --csv rename id,user_id then reorder -f user_id,name users.csv
```

---

## Stats and Group-By

```bash
# Mean, stddev, percentiles on a numeric field
mlr --csv stats1 -a mean,stddev,p50,p95 -f price sales.csv

# Group-by sum
mlr --csv stats1 -a sum,count -f amount -g category txns.csv

# Two-way group-by
mlr --csv stats1 -a mean -f latency -g region,endpoint requests.csv

# Frequency table for a categorical field
mlr --csv count-distinct -f status events.csv

# Top-N per group
mlr --csv top -n 3 -f amount -g category txns.csv
```

---

## Joins

```bash
# Inner join on a shared key
mlr --csv join -j user_id -f users.csv orders.csv

# Left-outer join (keep unmatched left records)
mlr --csv join --ul -j user_id -f users.csv orders.csv

# Different key names on each side
mlr --csv join -l id -r user_id -f users.csv orders.csv

# Join across formats (left CSV, right JSONL, output JSON)
mlr --icsv --ojson join -j user_id -f users.csv then put '$joined = true' orders.csv
```

---

## In-Place Editing

`-I` rewrites files in place (across any supported format).

```bash
# Add a computed column to every row in a CSV
mlr -I --csv put '$total = $qty * $price' orders.csv

# Bulk update across many files
mlr -I --csv put '$updated_at = "2026-01-01"' data/*.csv

# JSONL in-place
mlr -I --jsonl put '$processed = true' events.jsonl
```

---

## Multi-File and Pipeline Flows

```bash
# Concatenate CSVs with the same schema (headers merged)
mlr --csv cat sales-*.csv > all-sales.csv

# Per-file tagging then merge
mlr --csv put '$source = FILENAME' a.csv b.csv c.csv

# JSONL log analysis pipeline
mlr --jsonl filter '$level == "error"' then \
            cut -f ts,service,msg then \
            sort -f ts logs.jsonl

# Hand off to jq for deep JSON shaping
mlr --c2j cat data.csv | jq '[.[] | select(.score > 90)]'
```

---

## Anti-Patterns

```bash
# BAD: grep/awk on JSONL drops structure, breaks on embedded quotes/commas
grep '"level":"error"' events.jsonl | awk -F'"msg":"' '{print $2}'
# GOOD
mlr --jsonl filter '$level == "error"' then cut -f msg events.jsonl

# BAD: awk on CSV breaks on quoted fields containing commas
awk -F',' '$3 == "active" {print $1,$2}' users.csv
# GOOD
mlr --csv filter '$status == "active"' then cut -f id,name users.csv
```

---

## Common Idioms

| Task | mlr Expression |
|------|----------------|
| Count records | `mlr --csv count data.csv` |
| Distinct values of a column | `mlr --csv uniq -f status data.csv` |
| Sort numeric descending | `mlr --csv sort -nr amount data.csv` |
| Drop columns | `mlr --csv cut -x -f password,token data.csv` |
| Sample N rows | `mlr --csv sample -k 100 data.csv` |
| Reservoir sample (deterministic) | `mlr --csv --seed 42 sample -k 100 data.csv` |
| Header-only output | `mlr --csv --headerless-csv-output cat data.csv` |
| Tee to multiple formats | `mlr --icsv --ojson tee then ... data.csv` |
| Read from stdin | `cat data.csv \| mlr --csv cat` |
| Read gzip directly | `mlr --csv --gzin cat data.csv.gz` |
